"""Deterministic report metrics - analysis_result.json (parsed) in, typed metrics dict out.

Layer 1 (and the template-formatted half of Layer 3) of the insight-driven
report described in docs/plans/2026-09-02-insight-driven-report.md, Sequencing
steps 1-3 only. Every number here is plain arithmetic over the already-analyzed
comments: reproducible from the JSON alone, auditable without re-running
anything, and computed with no network call. build_narrative() at the bottom
is plain Python %-formatting over these same numbers - not an LLM call. Layers
2 (LLM theme discovery, themes_llm.py) and the LLM half of Layer 3
(narrative_llm.py) from the plan are out of scope for this module by design
and are not built anywhere in report/.
"""
import random
import re

from collections import Counter, defaultdict
from functools import lru_cache
from math import log, sqrt
from typing import Any, Dict, FrozenSet, List, Optional, Tuple

from sosmed_sentiment.preprocessing.filtering import load_stopwords
# TIER_ORDER is a plain 4-tuple of tier-name strings (kol/official/affiliate/
# unknown) - importing the constant (not classify_tier itself) keeps this
# module free of any account-type classification logic (T-ENG-2: tiering
# stays html_builder's job) while avoiding a second hand-copied tuple that
# could silently drift from sampler.py's (the same DRY reasoning
# _keyword_stopwords()'s docstring gives for reusing filtering.py's list).
from tiktokcomment.sampler import TIER_ORDER

POS: str = 'positif'
NEG: str = 'negatif'
NEU: str = 'netral'
UNK: str = 'tidak_terklasifikasi'
CLASSIFIED_LABELS: Tuple[str, str, str] = (POS, NEG, NEU)

# A month with fewer than this many comments swings wildly on one viral video -
# dropped from the trend so a thin month doesn't masquerade as a real signal.
MIN_MONTH_VOLUME: int = 20
# A video with fewer than this many classified comments can flip from best to
# worst on a single comment - excluded from the ranked leaderboard (still
# counted in totals, just not ranked).
MIN_VIDEO_COMMENTS: int = 30
# Jeffreys log-odds needs enough document-frequency support per token to be a
# stable ranking rather than noise from one or two comments.
MIN_KEYWORD_DOC_COUNT: int = 15
KEYWORD_MIN_LENGTH: int = 3
KEYWORDS_PER_LABEL: int = 12
TOP_COMMENTS_PER_LABEL: int = 8
VIDEO_LEADERBOARD_SIZE: int = 8
# TD-4: the comment explorer ships on by default but hard-capped, server
# rendered directly into the template rather than an empty <div> filled only
# by JavaScript (a verified defect in the reference report).
EXPLORER_ROW_CAP: int = 150
# E-5: a local RNG, never the global random.seed() - so this module's
# determinism cannot leak into (or depend on) anything else importing random.
EXPLORER_RNG_SEED: int = 7
# T-ENG-4: how many representative example comments a per-tier deep-dive
# block shows - 3-5 per the spec's requirement #6, sorted by digg_count.
TIER_EXAMPLE_COMMENTS_LIMIT: int = 5
# Below this, a per-tier deep-dive block's example-comment count gets a
# quiet "hanya N komentar tersedia" note instead of silently padding/hiding.
TIER_EXAMPLE_COMMENTS_MIN: int = 3

MONTH_NAMES_ID: Tuple[str, ...] = (
    'Jan', 'Feb', 'Mar', 'Apr', 'Mei', 'Jun', 'Jul', 'Agu', 'Sep', 'Okt', 'Nov', 'Des'
)

# T-ENG-5: display names for the always-present 4-tier deep dive, kept local
# to this module (same precedent as MONTH_NAMES_ID above - plain Indonesian
# display strings used only in %-formatted prose/labels, not a rendering
# concern). Deliberately distinct from html_builder.TIER_LABELS's 'Unknown'
# used by the pre-existing scorecard (FT-1, untouched by this feature) - the
# spec calls for "Tidak diketahui" specifically for the new deep-dive bucket.
TIER_LABELS_ID: Dict[str, str] = {
    'kol': 'KOL', 'official': 'Official', 'affiliate': 'Affiliate', 'unknown': 'Tidak diketahui'
}

# T-ENG-3: six named theme categories, literal-alternation + word-boundary +
# re.escape()'d per token (D12 - closes ReDoS/false-positive risk), matched
# against tokens_stemmed (cheap, already-tokenized, structurally immune to
# backtracking blowup) rather than raw text_raw. Themes are NOT mutually
# exclusive per comment (D7) - a comment can match more than one.
def _theme_pattern(*tokens: str) -> Any:
    return re.compile(r'\b(?:%s)\b' % '|'.join(re.escape(token) for token in tokens))


THEME_PATTERNS: Dict[str, Any] = {
    'dosage_usage': _theme_pattern('minum', 'sendok', 'botol', 'campur', 'konsumsi'),
    'price_availability': _theme_pattern('harga', 'beli', 'order', 'cod'),
    'age_eligibility': _theme_pattern(
        'umur', 'usia', 'tahun', 'bulan', 'bb', 'tinggi', 'stunting'
    ),
    'safety_side_effects': _theme_pattern('efek', 'samping', 'alergi', 'aman', 'reaksi'),
    'result_complaints': _theme_pattern('hasil', 'ngefek', 'naik', 'turun'),
    'counterfeit_authenticity': _theme_pattern('asli', 'palsu', 'ori', 'tiru')
}

THEME_LABELS_ID: Dict[str, str] = {
    'dosage_usage': 'Dosis & cara pakai',
    'price_availability': 'Harga & tempat beli',
    'age_eligibility': 'Usia & kelayakan',
    'safety_side_effects': 'Efek samping & keamanan',
    'result_complaints': "Hasil tidak terasa / tidak ngefek",
    'counterfeit_authenticity': 'Keaslian & barang palsu'
}


@lru_cache(maxsize=1)
def _keyword_stopwords() -> FrozenSet[str]:
    """DEFAULT_STOPWORDS minus NEGATION_WORDS, loaded once via filtering.py.

    Rules.md Sec 2 (absolute): negation words must never be filtered out of
    any downstream analysis. tokens_stemmed already passed through this exact
    filter during preprocessing; this second pass exists only because keyword
    ranking here works off a fresh per-label Counter and must never hand-write
    a second stopword list that could silently drift from filtering.py's (the
    reference script's bug, E-1 in the plan's eng review - its own STOP list
    stripped 'tidak' and 'belum', making "tidak ngefek" and "ngefek" the same
    evidence for exactly the analysis meant to tell them apart).
    """
    return frozenset(load_stopwords(None))


def classified_base(counts: Dict[str, int]) -> int:
    """The ONE denominator for every net-sentiment figure in this report.

    positif + negatif + netral - excludes tidak_terklasifikasi. Used for the
    KPI, the trend, and every per-video net score, with no exception. A
    verified defect in the reference script (plan E-2) used this base for the
    KPI card but sum(all label counts) - including unclassified - for the
    trend, so the two numbers silently answered different questions. Routing
    every net-score call through this one function closes that gap
    structurally instead of by convention.
    """
    return counts.get(POS, 0) + counts.get(NEG, 0) + counts.get(NEU, 0)


def net_score(pos: int, neg: int, base: int) -> float:
    """%positif - %negatif over `base`, which must be classified_base()'s result. -100..100."""
    return round(100.0 * (pos - neg) / base, 1) if base else 0.0


def _pct(count: int, total: int) -> float:
    return round(100.0 * count / total, 1) if total else 0.0


def _id_number(value: int) -> str:
    """1234567 -> '1.234.567' - Indonesian thousands separator for narrative prose."""
    return '{:,}'.format(value).replace(',', '.')


def _label_counts(comments: List[Dict[str, Any]]) -> Counter:
    return Counter(c.get('sentiment_label', UNK) for c in comments)


def _monthly_trend(comments: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Per-month sentiment counts and net score - genuinely re-derived per month.

    Deliberately NOT pooled into a single "last N months" headline. UC-6 in
    the plan's Phase 4 decisions found the reference's pooled 3-month figure
    ("+14.5 naik") printed the opposite of what the per-month series actually
    showed (+36.2 -> +36.9 -> +12.2, the newest month down 24.7 points).
    Pooling hides exactly the reversal a trend section exists to surface, so
    this function returns the real series and nothing else derives a blended
    figure from it.
    """
    by_month: Dict[str, Counter] = defaultdict(Counter)
    for comment in comments:
        create_time = comment.get('create_time')
        if not create_time or len(create_time) < 7:
            continue
        by_month[create_time[:7]][comment.get('sentiment_label', UNK)] += 1

    rows: List[Dict[str, Any]] = []
    for month in sorted(by_month):
        counts = by_month[month]
        total = sum(counts.values())
        if total < MIN_MONTH_VOLUME:
            continue
        base = classified_base(counts)
        year, month_num = month.split('-')
        rows.append({
            'month': month,
            'label': '%s %s' % (MONTH_NAMES_ID[int(month_num) - 1], year[2:]),
            'total': total,
            'pos': counts.get(POS, 0),
            'neg': counts.get(NEG, 0),
            'neu': counts.get(NEU, 0),
            'unk': counts.get(UNK, 0),
            'net': net_score(counts.get(POS, 0), counts.get(NEG, 0), base)
        })

    return rows


def _trend_last_delta(trend: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Newest month vs. the one immediately before it - two real months, never pooled."""
    if len(trend) < 2:
        return None

    latest, previous = trend[-1], trend[-2]
    return {
        'from_label': previous['label'],
        'to_label': latest['label'],
        'from_net': previous['net'],
        'to_net': latest['net'],
        'delta': round(latest['net'] - previous['net'], 1)
    }


def _engagement(comments: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Like-weighted net sentiment, and how much of it rides on the ten loudest comments."""
    total_likes: int = sum(comment.get('digg_count') or 0 for comment in comments)

    like_weighted: Counter = Counter()
    for comment in comments:
        like_weighted[comment.get('sentiment_label', UNK)] += comment.get('digg_count') or 0
    base = classified_base(like_weighted)
    net_by_likes = net_score(like_weighted.get(POS, 0), like_weighted.get(NEG, 0), base)

    liked_sorted = sorted(comments, key=lambda c: -(c.get('digg_count') or 0))
    top10_likes = sum((c.get('digg_count') or 0) for c in liked_sorted[:10])
    top10_share = _pct(top10_likes, total_likes)

    rest_weighted: Counter = Counter()
    for comment in liked_sorted[10:]:
        rest_weighted[comment.get('sentiment_label', UNK)] += comment.get('digg_count') or 0
    rest_base = classified_base(rest_weighted)
    net_by_likes_trimmed = net_score(
        rest_weighted.get(POS, 0), rest_weighted.get(NEG, 0), rest_base
    )

    return {
        'total_likes': total_likes,
        'net_by_likes': net_by_likes,
        'net_by_likes_trimmed': net_by_likes_trimmed,
        'top10_like_share_pct': top10_share
    }


def _top_comments(comments: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """Most-liked comments per sentiment label - the ones every new viewer reads first."""
    by_label: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for comment in comments:
        by_label[comment.get('sentiment_label', UNK)].append(comment)

    result: Dict[str, List[Dict[str, Any]]] = {}
    for label in (POS, NEG):
        ranked = sorted(by_label.get(label, []), key=lambda c: -(c.get('digg_count') or 0))
        result[label] = [
            {
                'username': comment.get('username', ''),
                'text_raw': comment.get('text_raw', ''),
                'digg_count': comment.get('digg_count') or 0,
                'create_time': (comment.get('create_time') or '')[:10],
                'sentiment_method': comment.get('sentiment_method', '')
            }
            for comment in ranked[:TOP_COMMENTS_PER_LABEL]
        ]

    return result


def _keyword_tokens(comment: Dict[str, Any]) -> List[str]:
    stopwords = _keyword_stopwords()
    return [
        token for token in (comment.get('tokens_stemmed') or [])
        if token not in stopwords and len(token) > KEYWORD_MIN_LENGTH
    ]


def _weighted_log_odds(
    target: List[Dict[str, Any]],
    comparison: List[Dict[str, Any]],
    *, limit: int = KEYWORDS_PER_LABEL
) -> List[Dict[str, Any]]:
    """Jeffreys-style weighted log-odds ranking of `target`'s vocabulary against
    `comparison`'s pooled vocabulary.

    TD-9: the primitive both _distinctive_keywords() (per sentiment label)
    and _distinctive_keywords_by_tier() (per account-type tier) route
    through, so the two ranking concepts cannot silently drift apart the way
    classified_base()'s docstring warns a second hand-rolled implementation
    always eventually does.

    A defensible approximation, not Monroe et al.'s informative Dirichlet-prior
    method: a flat +0.5 prior and the standard sqrt(1/a + 1/b) variance
    estimate (E-3 in the plan's eng review - labeled here as what it actually
    is, not oversold). Counts are document frequency (each comment votes at
    most once per token, via set()), not term frequency.

    `comparison` is a plain list of already-filtered comments, not a label or
    tier name - callers decide what universe to compare against. Both
    existing callers pass a comparison pool that includes `target`'s own
    comments (D4: matches the pre-existing per-label convention exactly,
    documented explicitly here so a future reviewer does not "fix" this into
    a target-excluded comparison by mistake). Returns [] when `target` is
    empty - never divides by a zero n_target.
    """
    target_doc_counts: Counter = Counter()
    for comment in target:
        target_doc_counts.update(set(_keyword_tokens(comment)))
    n_target = sum(target_doc_counts.values())
    if n_target == 0:
        return []

    comparison_doc_counts: Counter = Counter()
    for comment in comparison:
        comparison_doc_counts.update(set(_keyword_tokens(comment)))
    n_all = sum(comparison_doc_counts.values())
    n_other = max(n_all - n_target, 0)

    rows: List[Dict[str, Any]] = []
    for word, c_target in target_doc_counts.items():
        if c_target < MIN_KEYWORD_DOC_COUNT:
            continue
        c_all = comparison_doc_counts.get(word, c_target)
        c_other = max(c_all - c_target, 0)
        p_target = (c_target + 0.5) / (n_target + 1)
        p_other = (c_other + 0.5) / (n_other + 1)
        log_odds = log(p_target / (1 - p_target)) - log(p_other / (1 - p_other))
        std_err = sqrt(1 / (c_target + 0.5) + 1 / (c_other + 0.5))
        rows.append({
            'keyword': word,
            'score': round(log_odds / std_err, 2) if std_err else 0.0,
            'count': c_target,
            'share_pct': _pct(c_target, c_target + c_other)
        })

    rows.sort(key=lambda row: -row['score'])
    return rows[:limit]


def _distinctive_keywords(comments: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """Jeffreys-style weighted log-odds keyword ranking, one list per sentiment label.

    A thin wrapper over _weighted_log_odds() (T-ENG-1) - public signature and
    behavior unchanged from before the generalization. Comparison pool is the
    classified comments only (positif+negatif+netral, tidak_terklasifikasi
    excluded) - the pre-existing convention, preserved exactly.

    Negation words are never stripped: _keyword_stopwords() is
    DEFAULT_STOPWORDS - NEGATION_WORDS imported from preprocessing.filtering,
    never a second hand-written list (Rules.md Sec 2, E-1). "tidak ngefek"
    stays distinguishable from "ngefek".
    """
    classified_comments: List[Dict[str, Any]] = [
        comment for comment in comments if comment.get('sentiment_label', UNK) in CLASSIFIED_LABELS
    ]
    by_label: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for comment in classified_comments:
        by_label[comment['sentiment_label']].append(comment)

    return {
        label: _weighted_log_odds(by_label.get(label, []), classified_comments, limit=KEYWORDS_PER_LABEL)
        for label in CLASSIFIED_LABELS
    }


def _distinctive_keywords_by_tier(
    comments_by_tier: Dict[str, List[Dict[str, Any]]]
) -> Dict[str, List[Dict[str, Any]]]:
    """Per-account-type-tier distinctive keywords - same primitive as
    _distinctive_keywords(), a different grouping dimension (T-ENG-2).

    Takes already-tiered comment lists (comments_by_tier: tier name -> list)
    rather than raw comments + a classify_tier() call - keeps this module
    free of any account-type classification logic, which stays html_builder's
    job (matching the existing account_type_map plumbing there).

    Comparison pool (D4): the FULL corpus - every tier's comments including
    the target tier's own, and including tidak_terklasifikasi-labeled
    comments (unlike _distinctive_keywords()'s per-label convention, which
    excludes unclassified comments entirely). This is a deliberate
    difference, not an inconsistency: a sentiment label's natural comparison
    universe is "everything classified", while a tier's natural comparison
    universe is "every comment regardless of sentiment outcome".
    """
    all_comments: List[Dict[str, Any]] = [
        comment for group in comments_by_tier.values() for comment in group
    ]
    return {
        tier: _weighted_log_odds(group, all_comments, limit=KEYWORDS_PER_LABEL)
        for tier, group in comments_by_tier.items()
    }


def _theme_matches(comments: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Per-theme match count + share_pct over `comments`, sorted by frequency
    descending (dict insertion order, T-ENG-3). Themes are independent counts
    (D7) - one comment can match more than one theme.

    Matched against tokens_stemmed (joined back into a single string so a
    \\b-bounded pattern can search across the whole token list in one pass),
    not text_raw - cheaper and structurally immune to the ReDoS class of risk
    a raw-text alternation-of-alternations pattern would carry (D12).
    """
    total: int = len(comments)
    counts: Dict[str, int] = {key: 0 for key in THEME_PATTERNS}

    for comment in comments:
        joined: str = ' '.join(comment.get('tokens_stemmed') or [])
        for key, pattern in THEME_PATTERNS.items():
            if pattern.search(joined):
                counts[key] += 1

    ordered_keys = sorted(THEME_PATTERNS, key=lambda key: -counts[key])
    return {
        key: {
            'theme': key,
            'label': THEME_LABELS_ID[key],
            'count': counts[key],
            'share_pct': _pct(counts[key], total)
        }
        for key in ordered_keys
    }


def _tier_example_comments(
    comments: List[Dict[str, Any]],
    limit: int = TIER_EXAMPLE_COMMENTS_LIMIT
) -> List[Dict[str, Any]]:
    """3-5 representative comments for a tier, most-liked first (T-ENG-4).

    Analogous to _top_comments() but not sentiment-label-scoped. Ties on
    digg_count break deterministically on comment_id (falls back to username
    then text_raw when comment_id is absent, so ordering never depends on
    dict/list iteration order) rather than leaving Python's stable sort to
    resolve ties by original list order, which is really "input order",
    not a real tiebreak. Returns fewer than `limit` without padding when the
    tier genuinely has fewer comments; [] when the tier is empty.
    """
    ranked = sorted(
        comments,
        key=lambda c: (
            -(c.get('digg_count') or 0),
            str(c.get('comment_id') or ''),
            c.get('username', ''),
            c.get('text_raw', '')
        )
    )
    return [
        {
            'username': comment.get('username', ''),
            'text_raw': comment.get('text_raw', ''),
            'digg_count': comment.get('digg_count') or 0,
            'create_time': (comment.get('create_time') or '')[:10],
            'sentiment_label': comment.get('sentiment_label', UNK)
        }
        for comment in ranked[:limit]
    ]


def _build_tier_narrative(
    tier: Dict[str, Any],
    others: List[Dict[str, Any]]
) -> List[Dict[str, str]]:
    """1-2 %-formatted sentences comparing one tier's dict against the others
    (T-ENG-5, requirement #7) - plain Python string formatting like every
    other sentence build_narrative() produces elsewhere in this module, not
    an LLM call. `tier` and each entry of `others` share the shape produced
    by _build_tier_deep_dive() below.

    Degenerate case (this tier is the only one with any comments): there is
    nothing to compare against, so the sentence says that plainly instead of
    dividing by an empty `others` list.
    """
    if not others:
        return [{
            'title': '%s adalah satu-satunya tipe akun dengan data' % tier['label'],
            'body': (
                '%s komentar dari %d video pada tipe akun %s - tidak ada tipe akun lain pada '
                'dataset ini untuk dibandingkan.' % (
                    _id_number(tier['comment_count']), tier['video_count'], tier['label']
                )
            )
        }]

    avg_other_net: float = sum(other['net'] for other in others) / len(others)
    diff: float = round(tier['net'] - avg_other_net, 1)
    direction: str = 'lebih tinggi' if diff > 0 else ('lebih rendah' if diff < 0 else 'setara')

    sentences: List[Dict[str, str]] = [{
        'title': 'Net sentimen %s: %+.1f' % (tier['label'], tier['net']),
        'body': (
            '%s poin %s dibanding rata-rata tipe akun lain (%+.1f), dari %s komentar '
            '(%s%% dari seluruh komentar) di %d video.' % (
                ('%.1f' % abs(diff)), direction, avg_other_net,
                _id_number(tier['comment_count']), tier['pct_of_total'], tier['video_count']
            )
        )
    }]

    if tier['themes']:
        top_theme = tier['themes'][0]
        if top_theme['count']:
            sentences.append({
                'title': 'Tema paling banyak disebut: %s' % top_theme['label'],
                'body': (
                    'Muncul di %s komentar (%s%% dari komentar tipe akun ini).' % (
                        _id_number(top_theme['count']), top_theme['share_pct']
                    )
                )
            })

    return sentences


def _build_tier_deep_dive(
    comments_by_tier: Dict[str, List[Dict[str, Any]]],
    video_counts: Optional[Dict[str, int]] = None
) -> List[Dict[str, Any]]:
    """Assembles every per-tier deep-dive requirement (#1-#7) into one row per
    tier, ordered by comment volume descending (TD-8) - kol/official/
    affiliate/unknown ("Tidak diketahui") ALWAYS all four, even a tier with
    zero comments (D8: the spec's "never silently drop the unknown bucket"
    requirement, verified defensively even though this dataset's account_type
    values happen to classify 100% into kol/official/affiliate today).

    Takes already-tiered comment lists (comments_by_tier), same reasoning as
    _distinctive_keywords_by_tier() above - classify_tier() stays out of this
    module. Called from html_builder.build_report() rather than from
    build_metrics() itself, because build_metrics() has no account_type_map
    to tier by (that plumbing is html_builder's, not insights.py's) - a
    documented, deliberate deviation from the plan's literal "called once
    from build_metrics()" wiring note, not from its architecture constraint
    (T-ENG-2's "no classify_tier import into insights.py" is honored exactly).

    video_counts (tier -> count), when given, overrides the video count this
    function would otherwise derive from comments_by_tier's own video_id
    values. html_builder passes the full account_type_map-derived distribution
    (matches _tier_breakdown()'s same fix - see html_builder._tier_video_counts)
    - the comment-derived count alone only ever covers videos that happen to
    have an analyzed comment, undercounting requirement #1's "video count" on
    a real dataset where most scraped videos aren't in the analyzed sample.
    Passed in before the narrative sentences are built (not patched onto the
    result afterward) so a narrative sentence never cites a different video
    count than the KPI strip above it.
    """
    video_counts = video_counts or {}
    all_comments: List[Dict[str, Any]] = [
        comment for group in comments_by_tier.values() for comment in group
    ]
    total_all: int = len(all_comments)

    rows_by_tier: Dict[str, Dict[str, Any]] = {}
    for tier in TIER_ORDER:
        group: List[Dict[str, Any]] = comments_by_tier.get(tier) or []
        total: int = len(group)
        if tier in video_counts:
            video_count = video_counts[tier]
        else:
            video_count = len({str(c['video_id']) for c in group if c.get('video_id')})

        label_counts = _label_counts(group)
        sentiment_counts = {label: label_counts.get(label, 0) for label in (POS, NEG, NEU, UNK)}
        base = classified_base(sentiment_counts)
        sentiment_pct = {
            'positif_pct': _pct(sentiment_counts[POS], total),
            'negatif_pct': _pct(sentiment_counts[NEG], total),
            'netral_pct': _pct(sentiment_counts[NEU], total),
            'unclassified_pct': _pct(sentiment_counts[UNK], total)
        }
        net = net_score(sentiment_counts[POS], sentiment_counts[NEG], base)
        themes = list(_theme_matches(group).values())
        examples = _tier_example_comments(group)

        rows_by_tier[tier] = {
            'tier': tier,
            'label': TIER_LABELS_ID.get(tier, tier.title()),
            'video_count': video_count,
            'comment_count': total,
            'pct_of_total': _pct(total, total_all),
            'sentiment_counts': sentiment_counts,
            'sentiment_pct': sentiment_pct,
            'net': net,
            'themes': themes,
            'examples': examples,
            'examples_short': len(examples) < TIER_EXAMPLE_COMMENTS_MIN
        }

    keywords_by_tier = _distinctive_keywords_by_tier(comments_by_tier)
    for tier in TIER_ORDER:
        rows_by_tier[tier]['keywords'] = keywords_by_tier.get(tier, [])

    ordered_tiers: List[str] = sorted(TIER_ORDER, key=lambda tier: -rows_by_tier[tier]['comment_count'])

    result: List[Dict[str, Any]] = []
    for tier in ordered_tiers:
        others = [
            rows_by_tier[other] for other in TIER_ORDER
            if other != tier and rows_by_tier[other]['comment_count'] > 0
        ]
        rows_by_tier[tier]['narrative'] = _build_tier_narrative(rows_by_tier[tier], others)
        result.append(rows_by_tier[tier])

    return result


def _video_leaderboard(per_video: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Best / worst / loudest videos by classified net sentiment, MIN_VIDEO_COMMENTS-floored."""
    if not per_video:
        return {
            'best': [], 'worst': [], 'loudest': [],
            'median_net': 0.0, 'eligible_count': 0, 'total_count': 0
        }

    videos: List[Dict[str, Any]] = []
    for video in per_video:
        counts = video.get('sentiment_summary') or {}
        base = classified_base(counts)
        if base == 0:
            continue
        videos.append({
            'video_id': video.get('video_id', ''),
            'caption': video.get('caption') or '(tanpa caption)',
            'total': base,
            'pos': counts.get(POS, 0),
            'neg': counts.get(NEG, 0),
            'neu': counts.get(NEU, 0),
            'net': net_score(counts.get(POS, 0), counts.get(NEG, 0), base)
        })

    eligible = [video for video in videos if video['total'] >= MIN_VIDEO_COMMENTS]
    worst = sorted(eligible, key=lambda video: (video['net'], -video['total']))[:VIDEO_LEADERBOARD_SIZE]
    best = sorted(eligible, key=lambda video: (-video['net'], -video['total']))[:VIDEO_LEADERBOARD_SIZE]
    loudest = sorted(videos, key=lambda video: -video['total'])[:VIDEO_LEADERBOARD_SIZE]
    median_net = sorted(video['net'] for video in eligible)[len(eligible) // 2] if eligible else 0.0

    return {
        'best': best,
        'worst': worst,
        'loudest': loudest,
        'median_net': median_net,
        'eligible_count': len(eligible),
        'total_count': len(videos)
    }


def _data_quality(
    data: Dict[str, Any],
    total_comments: int,
    unclassified: int
) -> Dict[str, Any]:
    breakdown: Dict[str, int] = (data.get('meta') or {}).get('sentiment_method_breakdown') or {}
    llm = breakdown.get('llm', 0)
    llm_failed = breakdown.get('llm_failed', 0)
    llm_traffic = llm + llm_failed

    return {
        'unclassified_count': unclassified,
        'unclassified_pct': _pct(unclassified, total_comments),
        'llm_escalation_pct': _pct(llm_traffic, total_comments),
        'llm_failure_pct': _pct(llm_failed, llm_traffic),
        'method_breakdown': dict(breakdown)
    }


def _explorer_rows(comments: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """A server-rendered sample, hard-capped at EXPLORER_ROW_CAP rows.

    TD-4: on by default, capped, and rendered directly into the template
    instead of an empty <div> filled only by JavaScript - the reference
    shipped that as a verified defect (unreadable without JS).

    Fix pass 2026-09-02b (FT-3): an unconditional "every negatif and
    tidak_terklasifikasi comment first" fill made the explorer structurally
    incapable of showing a positif or netral comment whenever those two
    labels alone filled the cap (all three review voices flagged this as a
    fabricated impression of the dataset, not mere sampling bias). A fixed
    per-label floor now runs first, in a fixed tuple order
    (CLASSIFIED_LABELS + (UNK,), never a dict/set - determinism, E-5)
    reserving min(EXPLORER_ROW_CAP // 4, available-for-that-label) slots,
    most-liked within the label. Unused floor capacity from a thin label
    rolls forward automatically (the floor stage just selects fewer rows).
    After the floor, the original priority order still applies over
    whatever's left: every remaining negatif/tidak_terklasifikasi comment,
    then the most-liked remainder, then a random fill - using a local
    random.Random instance (E-5), never the global random.seed(), so this
    function's determinism cannot leak into or depend on anything else that
    uses random.
    """
    rng = random.Random(EXPLORER_RNG_SEED)

    def key_of(comment: Dict[str, Any]) -> Any:
        return comment.get('comment_id') if comment.get('comment_id') is not None else id(comment)

    selected: Dict[Any, Dict[str, Any]] = {}
    floor = EXPLORER_ROW_CAP // 4

    by_label: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for comment in comments:
        by_label[comment.get('sentiment_label', UNK)].append(comment)

    for label in CLASSIFIED_LABELS + (UNK,):
        pool = by_label.get(label) or []
        if not pool:
            continue
        ranked = sorted(pool, key=lambda c: -(c.get('digg_count') or 0))
        for comment in ranked[:min(floor, len(ranked))]:
            if len(selected) >= EXPLORER_ROW_CAP:
                break
            selected[key_of(comment)] = comment

    remaining = [c for c in comments if key_of(c) not in selected]
    remaining_slots = EXPLORER_ROW_CAP - len(selected)
    if remaining_slots > 0 and remaining:
        for comment in remaining:
            if len(selected) >= EXPLORER_ROW_CAP:
                break
            if comment.get('sentiment_label') in (NEG, UNK):
                selected[key_of(comment)] = comment

    remaining = [c for c in remaining if key_of(c) not in selected]
    remaining_slots = EXPLORER_ROW_CAP - len(selected)
    if remaining_slots > 0 and remaining:
        by_likes = sorted(remaining, key=lambda c: -(c.get('digg_count') or 0))
        for comment in by_likes[:remaining_slots]:
            selected[key_of(comment)] = comment

    remaining = [c for c in remaining if key_of(c) not in selected]
    remaining_slots = EXPLORER_ROW_CAP - len(selected)
    if remaining_slots > 0 and remaining:
        sample = remaining if len(remaining) <= remaining_slots else rng.sample(remaining, remaining_slots)
        for comment in sample:
            selected[key_of(comment)] = comment

    ordered = sorted(selected.values(), key=lambda c: -(c.get('digg_count') or 0))[:EXPLORER_ROW_CAP]
    return [
        {
            'text_raw': (comment.get('text_raw') or '')[:400],
            'sentiment_label': comment.get('sentiment_label', UNK),
            'digg_count': comment.get('digg_count') or 0,
            'create_time': (comment.get('create_time') or '')[:10],
            'sentiment_method': comment.get('sentiment_method', '')
        }
        for comment in ordered
    ]


def _trend_word(delta: float) -> str:
    if delta > 2:
        return 'naik'
    if delta < -2:
        return 'turun'
    return 'stabil'


def build_narrative(
    metrics: Dict[str, Any],
    total_population_videos: Optional[int] = None
) -> Dict[str, List[Dict[str, str]]]:
    """Deterministic template narrative - plain %-formatting over `metrics`, no LLM.

    This is the entirety of "Layer 3" for the shipped floor (plan Sequencing
    steps 1-3). The plan's Layers 2 and 3 describe an LLM writing this prose
    instead and proposing theme categories; that work is explicitly out of
    scope here - no themes_llm.py, no narrative_llm.py, no LLM/openai import
    anywhere in report/. Every sentence below cites a number already present
    in `metrics`, so there is nothing here a model could get wrong or invent.
    """
    counts = metrics['sentiment_counts']
    pct = metrics['sentiment_pct']
    base = metrics['classified_total']

    headline: List[Dict[str, str]] = [{
        'title': 'Sentimen bersih %+.1f' % metrics['net_overall'],
        'body': (
            'Dari %s komentar terklasifikasi: %s positif (%s%%), %s negatif (%s%%), '
            '%s netral (%s%%). Basis perhitungan untuk seluruh angka net sentimen di '
            'laporan ini: total komentar dikurangi yang tidak terklasifikasi.' % (
                _id_number(base),
                _id_number(counts[POS]), pct['positif_pct'],
                _id_number(counts[NEG]), pct['negatif_pct'],
                _id_number(counts[NEU]), pct['netral_pct']
            )
        )
    }]

    trend = metrics['trend']
    trend_delta = metrics['trend_last_delta']
    if trend and not trend_delta:
        headline.append({
            'title': 'Tren belum bisa dibandingkan',
            'body': (
                'Baru %d bulan yang melewati ambang minimum %d komentar - '
                'dibutuhkan setidaknya dua bulan untuk membandingkan arah.' % (
                    len(trend), MIN_MONTH_VOLUME
                )
            )
        })

    engagement = metrics['engagement']
    if engagement['total_likes']:
        headline.append({
            'title': 'Net sentimen tertimbang like: %+.1f' % engagement['net_by_likes'],
            'body': (
                'Sepuluh komentar teratas menyerap %s%% dari %s like yang terkumpul. '
                'Tanpa sepuluh komentar itu, net sentimen tertimbang like menjadi '
                '%+.1f (dibanding %+.1f per komentar apa adanya).' % (
                    engagement['top10_like_share_pct'],
                    _id_number(engagement['total_likes']),
                    engagement['net_by_likes_trimmed'],
                    metrics['net_overall']
                )
            )
        })

    risk: List[Dict[str, str]] = [{
        'title': '%s komentar tidak terklasifikasi (%s%%)' % (
            _id_number(metrics['data_quality']['unclassified_count']),
            metrics['data_quality']['unclassified_pct']
        ),
        'body': (
            'Semua angka net sentimen di laporan ini dihitung atas %s komentar '
            'terklasifikasi, bukan %s komentar total.' % (
                _id_number(base), _id_number(metrics['total_comments'])
            )
        )
    }]
    if trend_delta:
        # TD-5 (fix pass 2026-09-02b): demoted out of `headline` - all three
        # review voices converged on this independently. A caveat appended to
        # an already-bolded headline title reads as hedgy without actually
        # lowering a skimming reader's perceived confidence; the demoted note
        # under "Kualitas data" is where a stakeholder actually looks for
        # caveats. _monthly_trend's own docstring documents a prior
        # overclaiming incident (UC-6) - this module has form for this.
        word = _trend_word(trend_delta['delta'])
        title = (
            'Perbandingan bulan-ke-bulan: %s %s dibanding %s (%+.1f poin) '
            '— belum diverifikasi terhadap populasi penuh' % (
                trend_delta['to_label'], word, trend_delta['from_label'], trend_delta['delta']
            )
        )
        if total_population_videos:
            body = (
                'Sampel video di laporan ini adalah sebagian kecil dari total video akun '
                '(~%s dari ~%s). Angka ini adalah sinyal awal dari sampel yang ada, bukan '
                'kesimpulan yang divalidasi terhadap seluruh populasi video — gunakan '
                'dengan hati-hati untuk keputusan besar.' % (
                    _id_number(metrics['sample_video_count']), _id_number(total_population_videos)
                )
            )
        else:
            body = (
                'Sampel video di laporan ini adalah sebagian dari total video akun; jumlah '
                'populasi penuh tidak disediakan pada run ini. Angka ini adalah sinyal awal '
                'dari sampel yang ada, bukan kesimpulan yang divalidasi terhadap seluruh '
                'populasi video — gunakan dengan hati-hati untuk keputusan besar.'
            )
        risk.append({'title': title, 'body': body})
    if metrics['data_quality']['llm_failure_pct']:
        risk.append({
            'title': 'Eskalasi LLM gagal %s%% dari trafik LLM' % metrics['data_quality']['llm_failure_pct'],
            'body': 'Kegagalan jalur LLM adalah sumber utama komentar tidak terklasifikasi di atas.'
        })

    actions: List[Dict[str, str]] = []
    video = metrics['video_leaderboard']
    if video['worst']:
        actions.append({
            'title': 'Audit video dengan net sentimen terendah',
            'body': (
                'Video terburuk berada di %+.0f, median video %+.0f dari %d video '
                'yang memenuhi ambang minimum %d komentar terklasifikasi.' % (
                    video['worst'][0]['net'], video['median_net'],
                    video['eligible_count'], MIN_VIDEO_COMMENTS
                )
            )
        })
    if not actions:
        actions.append({
            'title': 'Kumpulkan lebih banyak data sebelum mengambil keputusan',
            'body': (
                'Belum ada video yang memenuhi ambang minimum %d komentar '
                'terklasifikasi untuk diperingkat.' % MIN_VIDEO_COMMENTS
            )
        })

    return {'headline': headline, 'risk': risk, 'actions': actions}


def build_metrics(
    data: Dict[str, Any],
    total_population_videos: Optional[int] = None
) -> Dict[str, Any]:
    """analysis_result.json (already parsed) -> the full deterministic metrics dict.

    Every helper this calls is pure and reads only from `data`; this is the
    only place their outputs get combined. report/charts.py and the template
    read this dict, never the raw comments list directly - one place defines
    what a "metric" means in this report.

    total_population_videos (FT-2): an operator-supplied estimate of the
    account's TOTAL video count (not derivable from analysis_result.json,
    which only ever describes the sampled videos) - threaded through to
    build_narrative() so the demoted trend caveat can state how thin the
    sample is relative to the real population. None by default; the caveat
    then drops the specific ratio rather than printing a nonsensical
    "dari None video".
    """
    comments: List[Dict[str, Any]] = data.get('comments') or []
    total_comments = len(comments)
    sample_video_count = len({c['video_id'] for c in comments if c.get('video_id')})

    label_counts = _label_counts(comments)
    sentiment_counts = {label: label_counts.get(label, 0) for label in (POS, NEG, NEU, UNK)}
    base = classified_base(sentiment_counts)
    sentiment_pct = {
        'positif_pct': _pct(sentiment_counts[POS], total_comments),
        'negatif_pct': _pct(sentiment_counts[NEG], total_comments),
        'netral_pct': _pct(sentiment_counts[NEU], total_comments),
        'unclassified_pct': _pct(sentiment_counts[UNK], total_comments)
    }
    net_overall = net_score(sentiment_counts[POS], sentiment_counts[NEG], base)

    trend = _monthly_trend(comments)

    metrics: Dict[str, Any] = {
        'total_comments': total_comments,
        'classified_total': base,
        'sentiment_counts': sentiment_counts,
        'sentiment_pct': sentiment_pct,
        'net_overall': net_overall,
        'trend': trend,
        'trend_last_delta': _trend_last_delta(trend),
        'engagement': _engagement(comments),
        'top_comments': _top_comments(comments),
        'keywords_distinctive': _distinctive_keywords(comments),
        'video_leaderboard': _video_leaderboard(data.get('per_video') or []),
        'data_quality': _data_quality(data, total_comments, sentiment_counts[UNK]),
        'explorer_rows': _explorer_rows(comments),
        'sample_video_count': sample_video_count
    }
    metrics['narrative'] = build_narrative(metrics, total_population_videos)

    return metrics
