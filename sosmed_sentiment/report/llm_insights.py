"""LLM-generated narrative layer - metrics dict (aggregates only) in, a
{headline, risk, actions} narrative JSON out, guarded by a citation
validator before it is allowed to reach the report.

Second (and only other) LLM call site outside sentiment/llm_classifier.py,
per docs/plans/2026-09-04-llm-narrative-citation-guardrail.md Decision #2
and the Rules.md §3 amendment that same plan requires. Reuses
llm_classifier.py's client/retry SHAPE (OpenAI-compatible client,
LLM_API_KEY/LLM_BASE_URL from env, MAX_RETRIES-style backoff) but is not
imported from it - the two call sites have structurally different
contracts (1 comment -> 1 label vs. metrics dict -> narrative prose) and
different risk profiles (thousands of isolated per-comment calls there,
one single call that gates the whole report render here - Decision #24).

Never raises past this module's own boundary: every codepath either
returns a guardrail-accepted LLM narrative or falls back to
insights.build_narrative()/_build_tier_narrative() (deterministic, fresh
from this run's metrics). The narrative section of a report is NEVER
empty (Decision #4/#7, plan §2 "D4").
"""
import hashlib
import json
import os
import re
import time

from typing import Any, Dict, List, Optional, Set, Tuple

from loguru import logger
from openai import OpenAI

from sosmed_sentiment.errors import LLMCallError, NarrativeGuardrailError
from sosmed_sentiment.report import insights as insights_mod

# --- Transport-level retry (HTTP/timeout retry inside one LLM call) -------
# Named distinctly from the content-level (guardrail) retry below per
# Decision Audit Trail row #6/T6 - the two "retry" concepts are not the same
# thing and conflating them in code was flagged as a DRY/naming risk.
TRANSPORT_MAX_RETRIES: int = 2
TRANSPORT_RETRY_BACKOFF_SECONDS: Tuple[int, int] = (1, 3)
# Decision #24: llm_classifier.py intentionally has no request timeout
# (per-comment isolation makes one hang low-risk there). This module's one
# call gates the entire report render, so an explicit upper bound is
# required - an unbounded hang would block generate_report indefinitely,
# since the retry/fallback machinery below never gets control back until
# the call itself resolves. Raised from the original 30.0 after a real run
# against the operator's local router (nemotron-3-ultra-free, a reasoning
# model) measured ~26.5s for a TRIVIAL one-line prompt - 30s left almost no
# margin for the much larger narrative payload/prompt and was cutting the
# call short before the model finished reasoning. 120s gives a reasoning
# model room to actually respond instead of manufacturing a timeout failure.
REQUEST_TIMEOUT_SECONDS: float = 120.0

# Decision #23: mirrors insights.MIN_VIDEO_COMMENTS's reasoning ("is this
# subset of the corpus large enough to say something meaningful"), not
# MIN_MONTH_VOLUME's ("is this a whole calendar month"). Below this floor,
# the LLM call is skipped entirely (T5/T20) - a near-empty metrics dict
# produces a statistically meaningless narrative anyway.
MIN_NARRATIVE_VOLUME: int = 30

# Approach B (0C-bis, Decision #1): a claim using one of these connectors is
# rejected unless the connector's causal pairing is already present in the
# theme/keyword data sent to the LLM - the LLM may only ever restate a
# causal link insights.py's deterministic theme extraction already
# surfaced, never invent a new one. This closes S-5 (docs/plans/
# 2026-09-02-insight-driven-report.md), rated CRITICAL twice before this
# plan (docs/plans/2026-09-04-llm-narrative-citation-guardrail.md, User
# Challenges + 0C-bis). A living list, tuned as new Indonesian causal
# phrasing shows up - fails closed (over-rejection just triggers the D4
# fallback, never a false "safe" claim).
CAUSAL_CONNECTORS: Tuple[str, ...] = (
    'karena', 'disebabkan', 'menyebabkan', 'sebab', 'dikarenakan',
    'menunjukkan bahwa', 'sehingga', 'akibatnya', 'akibat dari', 'berdampak'
)

SYSTEM_PROMPT: str = (
    'Anda menulis narasi ringkas Bahasa Indonesia untuk laporan analisis sentimen '
    'sosial media internal. Anda HANYA boleh memakai angka yang benar-benar ada di '
    'data JSON yang diberikan pengguna - jangan pernah mengarang angka atau '
    'membulatkan secara berlebihan. Anda HANYA boleh mendeskripsikan apa yang data '
    'tunjukkan; JANGAN menyimpulkan hubungan sebab-akibat (\'karena\', \'sehingga\', '
    '\'menunjukkan bahwa\', dst) kecuali hubungan itu sendiri sudah ada secara '
    'eksplisit di field "themes" data yang diberikan. Balas HANYA dengan JSON '
    'persis berformat {"headline": [{"title": "...", "body": "..."}], '
    '"risk": [{"title": "...", "body": "..."}], "actions": [{"title": "...", '
    '"body": "..."}]} - tiap list minimal 1 item, jangan balas apapun selain '
    'JSON itu.'
)

NUMBER_RE = re.compile(r'[+-]?\d[\d.,]*\d|[+-]?\d+')

_NARRATIVE_SECTIONS: Tuple[str, ...] = ('headline', 'risk', 'actions')


class _NarrativeRejected(Exception):
    """Internal signal: guardrail-reject OR malformed-JSON, same rescue outcome.

    Decision Audit Trail row #7: a malformed response and a response with an
    unverifiable citation both need "retry once, then deterministic
    fallback" - modeling them as one internal signal here (raised as
    NarrativeGuardrailError to callers) avoids duplicating that retry/
    fallback logic for what is functionally the same rescue path.
    """


# --- Client (mirrors llm_classifier.py's _client() shape, not imported) ---

def _client(base_url: Optional[str], api_key: Optional[str]) -> OpenAI:
    """One OpenAI-compatible client, explicit timeout (Decision #24).

    api_key/base_url read from env by the caller (LLM_API_KEY, LLM_BASE_URL)
    - never hardcoded, never logged (Rules.md §7).
    """
    return OpenAI(api_key=api_key, base_url=base_url or None, timeout=REQUEST_TIMEOUT_SECONDS)


# --- Payload construction (Decision #5: aggregates + theme/keyword labels
# only, NEVER raw individual example quotes/comments) -----------------------

def build_payload(
    metrics: Dict[str, Any],
    tier_rows: Optional[List[Dict[str, Any]]] = None
) -> Dict[str, Any]:
    """metrics dict (insights.build_metrics()'s output) -> the SUBSET sent to
    the LLM. Aggregate numbers + short theme/keyword labels only - never a
    raw comment/quote (Decision #5). tier_rows, when given, is
    html_builder.build_tier_summary()'s output (or insights._build_tier_deep_
    dive()'s rows) - the per-tier net/video/comment counts + themes/keywords
    the guardrail later binds claims to (F1's entity-binding fix).
    """
    payload: Dict[str, Any] = {
        'net_overall': metrics['net_overall'],
        'classified_total': metrics['classified_total'],
        'total_comments': metrics.get('total_comments'),
        'sentiment_counts': dict(metrics['sentiment_counts']),
        'sentiment_pct': dict(metrics['sentiment_pct']),
        'data_quality': dict(metrics['data_quality']),
        'tier_breakdown': []
    }

    for row in (tier_rows or []):
        themes_source = row.get('top_themes') if 'top_themes' in row else row.get('themes')
        themes = [
            {
                'label': theme.get('theme') or theme.get('label'),
                'count': theme.get('count', 0)
            }
            for theme in (themes_source or [])
        ]
        keywords = [
            kw.get('keyword') for kw in (row.get('keywords_distinctive') or row.get('keywords') or [])
        ]
        payload['tier_breakdown'].append({
            'tier': row.get('tier', ''),
            'label': row.get('label', ''),
            'net': row.get('net', 0.0),
            'video_count': row.get('video_count', 0),
            'comment_count': row.get('total_count', row.get('comment_count', 0)),
            'pct_of_total': row.get('pct_of_total'),
            'themes': themes,
            'keywords': [kw for kw in keywords if kw]
        })

    return payload


# --- Cache key (Decision #4: sorted-key, fixed-float serialization) --------

def _stable_json(value: Any) -> Any:
    """Recursively round every float to a fixed precision and sort dict keys
    so two calls with the identical metrics subset always serialize to the
    same string (0E: naive dict hashing without sorted keys/fixed floats
    would silently miss the cache on identical runs).
    """
    if isinstance(value, float):
        return round(value, 4)
    if isinstance(value, dict):
        return {key: _stable_json(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        return [_stable_json(item) for item in value]
    return value


def cache_key(payload: Dict[str, Any]) -> str:
    """A stable hash of `payload` - identical metrics subsets always hash the
    same, any change anywhere in the subset changes the hash (auto-
    invalidation, Decision #4 - no manual cache-busting scheme needed for
    correctness, though --fresh-narrative stays as an explicit override).
    """
    canonical = json.dumps(_stable_json(payload), sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(canonical.encode('utf-8')).hexdigest()


def _atomic_write_json(path: str, data: Dict[str, Any]) -> None:
    """Write-to-tmp then os.replace() (Decision #26) - an interrupted write
    (Ctrl-C, disk full) must never leave a corrupt/partial file for the next
    run's cache-read to trip over.
    """
    directory = os.path.dirname(path) or '.'
    os.makedirs(directory, exist_ok=True)
    tmp_path = path + '.tmp'
    with open(tmp_path, 'w', encoding='utf-8') as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
    os.replace(tmp_path, path)


def _read_cache(cache_path: str, key: str) -> Optional[Dict[str, Any]]:
    """Cache-miss (including corrupt/unreadable file) is silent, never an
    error - just regenerate (Decision #4). A corrupt file is logged at
    WARNING (matches the plan's own failure-modes registry); a plain
    cache-miss (key mismatch, file absent) is silent.
    """
    if not cache_path or not os.path.exists(cache_path):
        return None
    try:
        with open(cache_path, encoding='utf-8') as handle:
            raw = json.load(handle)
    except (OSError, ValueError) as error:
        logger.warning(
            'narrative.json rusak/tidak terbaca (%s) - dianggap cache-miss, generate ulang' % error
        )
        return None
    if not isinstance(raw, dict) or raw.get('cache_key') != key:
        return None
    narrative = raw.get('narrative')
    if not isinstance(narrative, dict):
        return None
    return narrative


def _write_cache(cache_path: str, key: str, narrative: Dict[str, Any]) -> None:
    """Only ever caches a GUARDRAIL-ACCEPTED narrative - never a rejected
    draft, never the deterministic fallback silently mislabeled as cached-LLM
    (Decision #4). Callers must only invoke this after the guardrail passes.
    """
    if not cache_path:
        return
    try:
        _atomic_write_json(cache_path, {'cache_key': key, 'narrative': narrative})
    except OSError as error:
        logger.warning('gagal menulis narrative.json cache (%s) - lanjut tanpa cache' % error)


# --- JSON-shape/type validation (T13/Decision #19, FIRST guardrail step) --

def _validate_shape(parsed: Any) -> Dict[str, List[Dict[str, str]]]:
    """isinstance checks on headline/risk/actions structure, raising
    NarrativeGuardrailError directly - runs BEFORE any citation-parsing
    regex, so "syntactically valid JSON, wrong field TYPES" (a dict instead
    of a list, a non-string body, etc.) is a routine WARNING-level guardrail
    reject, not a raw TypeError/AttributeError that would otherwise only be
    caught by T2's top-level ERROR-level belt-and-suspenders catch.
    """
    if not isinstance(parsed, dict):
        raise NarrativeGuardrailError('respons LLM bukan objek JSON (%r)' % type(parsed).__name__)

    result: Dict[str, List[Dict[str, str]]] = {}
    for section in _NARRATIVE_SECTIONS:
        items = parsed.get(section)
        if not isinstance(items, list) or not items:
            raise NarrativeGuardrailError(
                'field "%s" hilang atau bukan list berisi minimal 1 item' % section
            )
        validated_items: List[Dict[str, str]] = []
        for index, item in enumerate(items):
            if not isinstance(item, dict):
                raise NarrativeGuardrailError(
                    '%s[%d] bukan objek (dict), dapat %r' % (section, index, type(item).__name__)
                )
            title, body = item.get('title'), item.get('body')
            if not isinstance(title, str) or not isinstance(body, str) or not body.strip():
                raise NarrativeGuardrailError(
                    '%s[%d] harus punya "title" dan "body" bertipe string tidak kosong' % (
                        section, index
                    )
                )
            validated_items.append({'title': title, 'body': body})
        result[section] = validated_items

    return result


# --- Citation guardrail (numeric membership + F1 entity-binding + causal
# connector allowlist) ------------------------------------------------------

def _parse_number_candidates(raw: str) -> List[float]:
    """A raw regex match like '1.234.567' or '+23.0' could be an Indonesian
    thousands-separated integer OR a plain decimal - try both
    interpretations rather than guessing, since the narrative prose mixes
    both conventions (insights._id_number() vs. net_score()'s %+.1f).
    """
    candidates: List[float] = []
    try:
        candidates.append(float(raw.replace(',', '.')))
    except ValueError:
        pass
    stripped = raw.replace('.', '').replace(',', '.')
    try:
        value = float(stripped)
        if value not in candidates:
            candidates.append(value)
    except ValueError:
        pass
    return candidates


def _flatten_payload_values(payload: Dict[str, Any]) -> List[Tuple[str, str, float]]:
    """(entity_label, field_name, value) for every number the payload
    carries - 'entity_label' is 'overall' for whole-report figures or a
    tier's display label for per-tier figures. This IS the flat set of
    valid values (§5 step 2's "numeric membership"); the entity_label lets
    _bind_claim() below refine flat membership into F1's entity-bound check.
    """
    flat: List[Tuple[str, str, float]] = []

    def add(entity: str, field: str, value: Any) -> None:
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            flat.append((entity, field, float(value)))

    add('overall', 'net_overall', payload.get('net_overall'))
    add('overall', 'classified_total', payload.get('classified_total'))
    add('overall', 'total_comments', payload.get('total_comments'))
    for field, value in (payload.get('sentiment_counts') or {}).items():
        add('overall', 'sentiment_counts.%s' % field, value)
    for field, value in (payload.get('sentiment_pct') or {}).items():
        add('overall', 'sentiment_pct.%s' % field, value)
    for field, value in (payload.get('data_quality') or {}).items():
        add('overall', 'data_quality.%s' % field, value)

    for tier in (payload.get('tier_breakdown') or []):
        entity = tier.get('label') or tier.get('tier') or ''
        add(entity, 'net', tier.get('net'))
        add(entity, 'video_count', tier.get('video_count'))
        add(entity, 'comment_count', tier.get('comment_count'))
        add(entity, 'pct_of_total', tier.get('pct_of_total'))
        for theme in (tier.get('themes') or []):
            add(entity, 'theme.%s' % theme.get('label'), theme.get('count'))

    return flat


def _entity_labels(payload: Dict[str, Any]) -> List[str]:
    labels = ['overall']
    for tier in (payload.get('tier_breakdown') or []):
        label = tier.get('label') or tier.get('tier')
        if label:
            labels.append(label)
    # Longest first so a substring label (e.g. "KOL" inside a longer label)
    # never wins over a more specific nearby match.
    return sorted(set(labels), key=len, reverse=True)


def _nearest_preceding_entity(body: str, position: int, entity_labels: List[str]) -> Optional[str]:
    """The entity label mentioned closest before `position` in `body`, or
    None if no entity label appears before this number at all (a
    whole-report claim with no tier context to bind to).
    """
    best_label: Optional[str] = None
    best_index = -1
    lowered = body.lower()
    for label in entity_labels:
        if label == 'overall':
            continue
        needle = label.lower()
        search_from = 0
        while True:
            index = lowered.find(needle, search_from, position)
            if index == -1:
                break
            if index > best_index:
                best_index = index
                best_label = label
            search_from = index + 1
    return best_label


def _match_tolerance(value: float) -> float:
    """Rounding tolerance: 1 decimal place worth of slack for report-scale
    figures, a little more for large counts formatted with thousands
    separators (Decision Audit Trail row #9's boundary-value framing).
    """
    return max(0.15, abs(value) * 0.001)


def _bind_claim_numbers(body: str, payload: Dict[str, Any]) -> Optional[str]:
    """F1: every number cited in `body` must bind to the CORRECT entity's
    value, not just exist somewhere in the flat payload. Returns None if
    every number binds correctly, or a human-readable reason string
    (surfaced in the WARNING log, CEO Section 8's "which claim failed" gap)
    on the first citation that doesn't.
    """
    flat = _flatten_payload_values(payload)
    if not flat:
        return None
    entity_labels = _entity_labels(payload)

    for match in NUMBER_RE.finditer(body):
        raw = match.group(0)
        candidates = _parse_number_candidates(raw)
        if not candidates:
            continue

        nearest_entity = _nearest_preceding_entity(body, match.start(), entity_labels)

        matches_any = [
            (entity, field, value) for entity, field, value in flat
            for candidate in candidates
            if abs(candidate - value) <= _match_tolerance(value)
        ]
        if not matches_any:
            return 'angka "%s" tidak ditemukan di metrics dict manapun' % raw

        if nearest_entity is not None:
            matches_entity = [row for row in matches_any if row[0] == nearest_entity]
            if not matches_entity:
                other = matches_any[0][0]
                return (
                    'angka "%s" ada di data tapi milik "%s", bukan "%s" yang disebut '
                    'di kalimat ini' % (raw, other, nearest_entity)
                )

    return None


def _causal_connector_in(body: str) -> Optional[str]:
    lowered = body.lower()
    for connector in CAUSAL_CONNECTORS:
        if connector in lowered:
            return connector
    return None


def _known_causal_terms(payload: Dict[str, Any]) -> Set[str]:
    """Theme/keyword labels already surfaced by insights.py's deterministic
    extraction - a causal claim is only allowed to restate a pairing that
    already lives here (Approach B, Decision #1), never invent a new one.
    """
    terms: Set[str] = set()
    for tier in (payload.get('tier_breakdown') or []):
        for theme in (tier.get('themes') or []):
            label = theme.get('label')
            if label:
                terms.add(str(label).lower())
        for keyword in (tier.get('keywords') or []):
            if keyword:
                terms.add(str(keyword).lower())
    return terms


def _causal_claim_supported(body: str, known_terms: Set[str]) -> bool:
    lowered = body.lower()
    return any(term in lowered for term in known_terms)


def _validate_claim(body: str, payload: Dict[str, Any], known_terms: Set[str]) -> Optional[str]:
    """One body string -> None (passes) or a reject reason. A body with zero
    numbers and no causal connector passes unconditionally (Section 4's
    explicitly-decided boundary case: pure description has nothing to
    validate, and rejecting all non-numeric prose would make the narrative
    unnaturally choppy).
    """
    numeric_reason = _bind_claim_numbers(body, payload)
    if numeric_reason:
        return numeric_reason

    connector = _causal_connector_in(body)
    if connector and not _causal_claim_supported(body, known_terms):
        return (
            'kalimat memakai kata penghubung sebab-akibat ("%s") tapi hubungan itu '
            'tidak ada di data tema/keyword yang dikirim ke LLM' % connector
        )

    return None


def run_citation_guardrail(narrative: Dict[str, List[Dict[str, str]]], payload: Dict[str, Any]) -> None:
    """§5 + F1 + Decision #1, whole-response reject (not partial-accept per
    §5 step 3 - simpler to verify, safer). Raises NarrativeGuardrailError
    with the FIRST failing claim's reason (CEO Section 8: "the log line
    should include which specific claim/number failed", not just a generic
    "guardrail rejected").
    """
    known_terms = _known_causal_terms(payload)
    for section in _NARRATIVE_SECTIONS:
        for item in narrative.get(section, []):
            reason = _validate_claim(item['body'], payload, known_terms)
            if reason:
                raise NarrativeGuardrailError(
                    'klaim narasi ditolak guardrail [%s] "%s": %s' % (
                        section, item.get('title', ''), reason
                    )
                )


# --- Transport-level LLM call (mirrors llm_classifier.py's retry shape) ---

def _call_llm_with_transport_retry(
    payload: Dict[str, Any],
    model: str,
    base_url: Optional[str],
    api_key: Optional[str]
) -> Any:
    """One narrative-generation HTTP call, retried up to TRANSPORT_MAX_RETRIES
    times on any transport failure before raising LLMCallError - the
    transport-level retry (network/timeout), distinct from the outer
    content-level (guardrail) retry T6 requires be named separately.
    """
    client = _client(base_url, api_key)
    last_error: Optional[Exception] = None
    user_content = json.dumps(payload, ensure_ascii=False)

    for attempt in range(1, TRANSPORT_MAX_RETRIES + 2):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {'role': 'system', 'content': SYSTEM_PROMPT},
                    {'role': 'user', 'content': user_content}
                ],
                temperature=0
            )
            if not response.choices:
                raise ValueError(
                    'respons LLM tidak berisi choices (kemungkinan endpoint '
                    'memotong jawaban di tengah proses "berpikir" - model '
                    'reasoning kadang butuh lebih dari %.0fs)' % REQUEST_TIMEOUT_SECONDS
                )
            content: str = response.choices[0].message.content or ''
            if not content.strip():
                raise ValueError(
                    'respons LLM kosong (message.content kosong) - '
                    'kemungkinan endpoint memotong jawaban sebelum model '
                    'selesai "berpikir" dan mengeluarkan jawaban final'
                )
            return json.loads(content)
        except Exception as error:  # noqa: BLE001 - any failure here is a retry candidate
            last_error = error
            if attempt <= TRANSPORT_MAX_RETRIES:
                low, high = TRANSPORT_RETRY_BACKOFF_SECONDS
                delay = low + (high - low) * (attempt - 1) / max(TRANSPORT_MAX_RETRIES - 1, 1)
                logger.warning(
                    'llm_insights: panggilan LLM narasi gagal (percobaan %d/%d) - %s - '
                    'kemungkinan penyebab: endpoint timeout/down atau respons bukan JSON valid - '
                    'mencoba ulang %.1fs lagi' % (
                        attempt, TRANSPORT_MAX_RETRIES + 1, error, delay
                    )
                )
                time.sleep(delay)

    raise LLMCallError(
        'llm_insights: panggilan LLM narasi gagal setelah %d percobaan (%s) - endpoint LLM '
        'kemungkinan down/timeout atau LLM_MODEL/LLM_BASE_URL salah - cek .env dan '
        'konektivitas ke router LLM, laporan tetap dibuat dengan narasi deterministik '
        'sebagai fallback' % (TRANSPORT_MAX_RETRIES + 1, last_error)
    )


def _generate_once(
    payload: Dict[str, Any],
    model: str,
    base_url: Optional[str],
    api_key: Optional[str]
) -> Dict[str, List[Dict[str, str]]]:
    """One full attempt: transport call -> shape validation (T13, FIRST) ->
    citation guardrail. Raises LLMCallError (transport) or
    NarrativeGuardrailError (shape/citation) - both routed through the same
    outer retry-then-fallback state machine (Decision #7).
    """
    raw = _call_llm_with_transport_retry(payload, model, base_url, api_key)
    narrative = _validate_shape(raw)
    run_citation_guardrail(narrative, payload)
    return narrative


# --- Outer content-level retry-then-fallback state machine (D4) -----------

BANNER_LLM_ACCEPTED: str = 'llm-accepted'
BANNER_RETRIED_THEN_FALLBACK: str = 'llm-retried-then-fallback'
BANNER_NO_LLM_CONFIGURED: str = 'no-llm-configured'
# Decision Audit Trail row #21/T15: --no-narrative gets its own explicit
# banner state rather than reusing no-llm-configured's text, which would
# read as "LLM wasn't configured" when it may well be - the operator
# deliberately opted out, a different fact worth stating plainly.
BANNER_NARRATIVE_DISABLED: str = 'narrative-disabled'
# Below MIN_NARRATIVE_VOLUME the LLM is never called (T5/T20) - distinct
# from "not configured" (an operator judgment call, documented in the final
# report: the plan's own 3 named states cover configuration/outcome, not
# "not enough data," so a 5th explicit state keeps that distinct rather than
# overloading one of the other four).
BANNER_BELOW_VOLUME_FLOOR: str = 'below-narrative-volume-floor'


def generate_narrative_with_guardrail(
    metrics: Dict[str, Any],
    tier_rows: Optional[List[Dict[str, Any]]] = None,
    total_population_videos: Optional[int] = None,
    model: Optional[str] = None,
    base_url: Optional[str] = None,
    api_key: Optional[str] = None,
    cache_path: Optional[str] = None,
    fresh: bool = False,
    no_narrative: bool = False
) -> Dict[str, Any]:
    """The single public entry point. Returns a dict:
      {'narrative': {...headline/risk/actions...}, 'status': one of the
       BANNER_* constants, 'source': 'llm'|'fallback', 'reject_reason':
       Optional[str] (set only when status is llm-retried-then-fallback and
       the cause was a guardrail reject, not a transport failure)}

    NEVER raises - the whole generate-and-guardrail call is wrapped in a
    top-level except Exception (T2/F2, CEO Section 2's one CRITICAL GAP)
    that unconditionally falls back to insights.build_narrative()/
    _build_tier_narrative(), logged at ERROR. D4's "narrative section is
    never empty" promise holds even if a bug escapes the inner retry/
    guardrail logic.
    """
    fallback_narrative = insights_mod.build_narrative(metrics, total_population_videos)

    if no_narrative:
        return {
            'narrative': fallback_narrative, 'status': BANNER_NARRATIVE_DISABLED,
            'source': 'fallback', 'reject_reason': None
        }

    model = model if model is not None else os.environ.get('LLM_MODEL', '')
    api_key = api_key if api_key is not None else os.environ.get('LLM_API_KEY', '')
    base_url = base_url if base_url is not None else os.environ.get('LLM_BASE_URL', '')

    if not (model and api_key):
        logger.info(
            'llm_insights: LLM_MODEL/LLM_API_KEY belum diisi - narasi laporan pakai versi '
            'deterministik apa adanya (isi .env kalau mau narasi yang ditulis LLM)'
        )
        return {
            'narrative': fallback_narrative, 'status': BANNER_NO_LLM_CONFIGURED,
            'source': 'fallback', 'reject_reason': None
        }

    if metrics.get('classified_total', 0) <= MIN_NARRATIVE_VOLUME:
        logger.info(
            'llm_insights: hanya %d komentar terklasifikasi (ambang minimum %d) - narasi LLM '
            'dilewati, dataset terlalu kecil untuk narasi yang bermakna secara statistik - '
            'pakai narasi deterministik' % (metrics.get('classified_total', 0), MIN_NARRATIVE_VOLUME)
        )
        return {
            'narrative': fallback_narrative, 'status': BANNER_BELOW_VOLUME_FLOOR,
            'source': 'fallback', 'reject_reason': None
        }

    payload = build_payload(metrics, tier_rows)
    key = cache_key(payload)

    if not fresh:
        cached = _read_cache(cache_path, key) if cache_path else None
        if cached is not None:
            logger.info('llm_insights: narasi diambil dari cache (narrative.json, hash cocok)')
            return {
                'narrative': cached, 'status': BANNER_LLM_ACCEPTED,
                'source': 'llm', 'reject_reason': None
            }

    reject_reason: Optional[str] = None
    try:
        try:
            narrative = _generate_once(payload, model, base_url, api_key)
            logger.info('llm_insights: narasi LLM lolos guardrail pada percobaan pertama')
        except (LLMCallError, NarrativeGuardrailError) as first_error:
            reject_reason = str(first_error)
            logger.warning(
                'llm_insights: narasi LLM ditolak/gagal pada percobaan pertama (%s) - '
                'kemungkinan penyebab: endpoint LLM tidak stabil atau LLM tidak patuh format '
                'JSON/guardrail - mencoba generate ulang satu kali sebelum fallback' % first_error
            )
            try:
                narrative = _generate_once(payload, model, base_url, api_key)
                logger.info('llm_insights: narasi LLM lolos guardrail pada percobaan kedua (retry)')
            except (LLMCallError, NarrativeGuardrailError) as second_error:
                reject_reason = str(second_error)
                logger.warning(
                    'llm_insights: narasi LLM ditolak/gagal lagi pada percobaan kedua (%s) - '
                    'fallback ke narasi deterministik untuk run ini (tidak mengubah default run '
                    'berikutnya) - cek log di atas untuk klaim/angka spesifik yang gagal' % second_error
                )
                return {
                    'narrative': fallback_narrative, 'status': BANNER_RETRIED_THEN_FALLBACK,
                    'source': 'fallback', 'reject_reason': reject_reason
                }

        if cache_path:
            _write_cache(cache_path, key, narrative)
        return {
            'narrative': narrative, 'status': BANNER_LLM_ACCEPTED,
            'source': 'llm', 'reject_reason': None
        }
    except Exception as error:  # noqa: BLE001 - T2/F2 belt-and-suspenders, D4 must never break
        logger.error(
            'llm_insights: kegagalan tak terduga di narrative generation (%s) - bug di '
            'llm_insights.py sendiri, bukan kegagalan LLM/guardrail yang sudah ditangani - '
            'fallback ke narasi deterministik, laporan tetap dibuat (lihat traceback di atas '
            'untuk debugging)' % error
        )
        return {
            'narrative': fallback_narrative, 'status': BANNER_RETRIED_THEN_FALLBACK,
            'source': 'fallback', 'reject_reason': reject_reason or str(error)
        }


# --- narrative_review.json audit sidecar (Decision #3) --------------------

def write_review_sidecar(
    path: str,
    status: str,
    generated_at: str,
    narrative: Dict[str, Any],
    reviewed_at: Optional[str] = None,
    reviewed_by: Optional[str] = None
) -> bool:
    """Atomic write (Decision #26). Write failure is caught, logged WARNING,
    never blocks the report (Decision #3 - sidecar is a quality signal, not
    a publish gate, matching D5's "not a gate" requirement). Returns True on
    success, False on a caught write failure.
    """
    data = {
        'generated_at': generated_at,
        'guardrail_status': status,
        'reviewed_at': reviewed_at,
        'reviewed_by': reviewed_by,
        'narrative': narrative
    }
    try:
        _atomic_write_json(path, data)
        return True
    except OSError as error:
        logger.warning(
            'llm_insights: gagal menulis narrative_review.json (%s) - direktori output mungkin '
            'tidak bisa ditulis - laporan HTML tetap tersimpan, sidecar audit ini hanya sinyal '
            'kualitas tambahan, bukan syarat publish' % error
        )
        return False


def read_review_sidecar(path: str) -> Optional[Dict[str, Any]]:
    if not path or not os.path.exists(path):
        return None
    try:
        with open(path, encoding='utf-8') as handle:
            return json.load(handle)
    except (OSError, ValueError) as error:
        logger.warning('llm_insights: narrative_review.json tidak terbaca (%s)' % error)
        return None
