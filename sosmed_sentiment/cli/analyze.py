import json
import os
import sys
import uuid

from typing import Any, Dict, List, Optional

import click
import yaml

from dotenv import load_dotenv
from loguru import logger

from sosmed_sentiment.errors import InvalidInputSchemaError, ModelClassifyError, ModelLoadError
from sosmed_sentiment.filters.exclude_accounts import apply_exclusions, detect_top_accounts
from sosmed_sentiment.ingest.tiktok_adapter import flatten_input
from sosmed_sentiment.keywords.tfidf_extractor import (
    extract_keywords_by_sentiment, extract_top_keywords
)
from sosmed_sentiment.output.serializer import build_analysis_result
from sosmed_sentiment.preprocessing.case_folding import case_fold
from sosmed_sentiment.preprocessing.cleaning import clean
from sosmed_sentiment.preprocessing.emoji import extract_emoji
from sosmed_sentiment.preprocessing.filtering import filter_stopwords, load_stopwords
from sosmed_sentiment.preprocessing.normalizing import normalize
from sosmed_sentiment.preprocessing.stemming import stem
from sosmed_sentiment.preprocessing.tokenizing import tokenize
from sosmed_sentiment.sentiment.hybrid import classify_comment, llm_failure_ratio_exceeds_threshold
from sosmed_sentiment.sentiment.model_classifier import (
    MODEL_NAME, MODEL_REVISION, classify as model_classify, load_model
)
from sosmed_sentiment.sentiment.threshold_config import load_threshold_config

__title__ = 'Sosmed Sentiment Pipeline - analyze'
__version__ = '0.1.0'

PROGRESS_LOG_EVERY: int = 500
CHECKPOINT_FIELDS: tuple = (
    'emoji_found', 'text_clean', 'tokens_stemmed',
    'sentiment_label', 'sentiment_confidence', 'sentiment_method'
)


class _Checkpoint:
    """Per-comment results appended as they finish, so a killed/timed-out run resumes.

    Same pattern as tiktokcomment/runner.py's Checkpoint - preprocessing+
    classification on ~6,000 comments takes ~20-25 minutes (stemming +
    model inference), long enough that a background job hitting a shell
    timeout or a killed process shouldn't mean starting over.
    """

    def __init__(
        self: '_Checkpoint',
        path: str
    ) -> None:
        self.path: str = path
        self.done: Dict[str, Dict[str, Any]] = {}

        if not os.path.exists(path):
            return

        with open(path, encoding='utf-8') as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry: Dict[str, Any] = json.loads(line)
                except ValueError:
                    continue
                if isinstance(entry, dict) and entry.get('comment_id'):
                    self.done[entry['comment_id']] = entry

    def add(
        self: '_Checkpoint',
        record: Dict[str, Any],
        hybrid_enabled: bool
    ) -> None:
        entry: Dict[str, Any] = {'comment_id': record['comment_id'], 'hybrid_enabled': hybrid_enabled}
        entry.update({field: record[field] for field in CHECKPOINT_FIELDS})
        self.done[record['comment_id']] = entry
        with open(self.path, 'a', encoding='utf-8') as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + '\n')

    def get(
        self: '_Checkpoint',
        comment_id: str,
        hybrid_enabled: bool
    ) -> Optional[Dict[str, Any]]:
        """Only reuse a cached result if it was classified under the same mode.

        A comment checkpointed model-only (no LLM escalation attempted) must
        not be silently reused once LLM_MODEL/LLM_API_KEY get configured on a
        later run - it was never evaluated against the escalation threshold,
        so reusing it would mix two different classification decisions in
        one output file with no signal that it happened. Entries written
        before this field existed (no 'hybrid_enabled' key) are treated as
        stale for the same reason - their mode is unknown, so it can't be
        trusted to match.
        """
        entry: Optional[Dict[str, Any]] = self.done.get(comment_id)
        if entry is None or entry.get('hybrid_enabled') != hybrid_enabled:
            return None
        return entry


def _load_exclude_list(
    path: str
) -> List[str]:
    if not path:
        return []

    with open(path, encoding='utf-8') as handle:
        data: Any = yaml.safe_load(handle) or {}

    return list(data.get('accounts') or [])


def _preprocess(
    text_raw: str
) -> Dict[str, Any]:
    """The fixed FR-03 stage order, run once per comment.

    Rules.md Aturan Mutlak: this order (emoji -> case_fold -> clean ->
    normalize -> tokenize -> filter -> stem) is not to be changed without
    discussion - it is not incidental.
    """
    without_emoji, emoji_found = extract_emoji(text_raw)
    folded = case_fold(without_emoji)
    cleaned = clean(folded)
    normalized = normalize(cleaned)
    tokens = tokenize(normalized)

    return {'emoji_found': emoji_found, 'text_clean': cleaned, 'tokens': tokens}


def run_analyze(
    input_path: str,
    output_path: str,
    exclude_config: str,
    stopwords_config: str,
    threshold_config: str = None,
    fresh: bool = False
) -> int:
    """The whole Modul 1 pipeline for one run. Returns the process exit code."""
    with open(input_path, encoding='utf-8') as handle:
        raw: Any = json.load(handle)

    try:
        flat: List[Dict[str, Any]] = flatten_input(raw)
    except InvalidInputSchemaError as error:
        logger.error(str(error))
        return 2

    total_raw: int = len(flat)

    exclude_list: List[str] = _load_exclude_list(exclude_config)
    apply_exclusions(flat, exclude_list)
    excluded_accounts_detected = detect_top_accounts(flat)

    analyzed: List[Dict[str, Any]] = [record for record in flat if not record['excluded']]
    logger.info(
        'ingest -> exclude: %d masuk -> %d setelah exclude' % (total_raw, len(analyzed))
    )

    stopwords = load_stopwords(stopwords_config)

    llm_model: str = os.environ.get('LLM_MODEL', '')
    llm_base_url: str = os.environ.get('LLM_BASE_URL', '')
    llm_api_key: str = os.environ.get('LLM_API_KEY', '')
    hybrid_enabled: bool = bool(llm_model and llm_api_key)

    threshold_confidence: Optional[float] = None
    if hybrid_enabled:
        try:
            threshold_confidence = load_threshold_config(threshold_config)
        except ValueError as error:
            logger.error(str(error))
            return 2
    else:
        logger.warning(
            'LLM_MODEL/LLM_API_KEY belum diisi - komentar dengan confidence model '
            'rendah TIDAK dieskalasi, cuma dipakai apa adanya (isi .env sebelum '
            'percaya hasil buat komentar ambigu)'
        )

    checkpoint_dir: str = os.path.dirname(output_path) or '.'
    os.makedirs(checkpoint_dir, exist_ok=True)
    checkpoint_path: str = os.path.join(checkpoint_dir, '.analyze-partial.jsonl')
    if fresh and os.path.exists(checkpoint_path):
        os.remove(checkpoint_path)
        logger.info('--fresh: cleared previous checkpoint')

    checkpoint = _Checkpoint(checkpoint_path)
    reusable: int = sum(
        1 for record in analyzed if checkpoint.get(record['comment_id'], hybrid_enabled) is not None
    )
    if reusable:
        logger.info('resuming - %d comment(s) already in checkpoint (same mode)' % reusable)

    if reusable < len(analyzed):
        try:
            load_model()
        except ModelLoadError as error:
            logger.error(str(error))
            return 2
    else:
        logger.info('every comment already in checkpoint - skipping model load')

    total: int = len(analyzed)
    for index, record in enumerate(analyzed, start=1):
        cached = checkpoint.get(record['comment_id'], hybrid_enabled)
        if cached is not None:
            record.update({field: cached[field] for field in CHECKPOINT_FIELDS})
        else:
            pre = _preprocess(record['text_raw'])
            filtered_tokens = filter_stopwords(pre['tokens'], stopwords)
            stemmed = stem(filtered_tokens)

            record['emoji_found'] = pre['emoji_found']
            record['text_clean'] = pre['text_clean']
            record['tokens_stemmed'] = stemmed

            if hybrid_enabled:
                result = classify_comment(
                    record['text_raw'], llm_model=llm_model, threshold_confidence=threshold_confidence,
                    base_url=llm_base_url or None, api_key=llm_api_key
                )
            else:
                try:
                    result = model_classify(record['text_raw'])
                except ModelClassifyError as error:
                    logger.warning('model classify gagal untuk satu komentar: %s' % error)
                    result = {
                        'sentiment_label': 'tidak_terklasifikasi',
                        'sentiment_confidence': 0.0,
                        'sentiment_method': 'model_failed'
                    }
            record.update(result)
            checkpoint.add(record, hybrid_enabled)

        if index % PROGRESS_LOG_EVERY == 0 or index == total:
            logger.info('preprocessing+sentiment: %d/%d komentar' % (index, total))

    logger.info(
        'preprocessing+sentiment: %d komentar diklasifikasi (%s)'
        % (len(analyzed), 'hybrid (model+llm)' if hybrid_enabled else 'model-only')
    )

    systemic_llm_failure: bool = llm_failure_ratio_exceeds_threshold(analyzed)

    joined_by_comment: List[str] = [' '.join(record['tokens_stemmed']) for record in analyzed]
    top_overall = extract_top_keywords(joined_by_comment, top_n=20)

    by_label: Dict[str, List[str]] = {}
    for record, joined in zip(analyzed, joined_by_comment):
        by_label.setdefault(record['sentiment_label'], []).append(joined)
    top_by_sentiment = extract_keywords_by_sentiment(by_label, top_n=10)

    result_json: Dict[str, Any] = build_analysis_result(
        run_id='run-%s' % uuid.uuid4().hex[:12],
        source_file=os.path.basename(input_path),
        total_comments_raw=total_raw,
        comments=analyzed,
        top_keywords_overall=top_overall,
        top_keywords_by_sentiment=top_by_sentiment,
        config_used={
            'model_version': '%s@%s' % (MODEL_NAME, MODEL_REVISION[:12]),
            'llm_base_url': os.environ.get('LLM_BASE_URL', ''),
            'llm_model': os.environ.get('LLM_MODEL', ''),
            'ambiguous_confidence_threshold': threshold_confidence,
            'exclude_config_file': exclude_config or ''
        },
        excluded_accounts_detected=excluded_accounts_detected
    )

    directory = os.path.dirname(output_path)
    if directory:
        os.makedirs(directory, exist_ok=True)

    with open(output_path, 'w', encoding='utf-8') as handle:
        json.dump(result_json, handle, ensure_ascii=False, indent=2)

    summary = result_json['sentiment_summary']
    logger.info(
        '==== Ringkasan Run ====\n'
        'Total komentar mentah   : %d\n'
        'Dikecualikan            : %d\n'
        'Dianalisis              : %d\n'
        'Sentimen: positif %d | negatif %d | netral %d\n'
        'Output tersimpan        : %s\n'
        '========================' % (
            total_raw, result_json['meta']['total_comments_excluded_internal'],
            len(analyzed), summary['positif'], summary['negatif'], summary['netral'],
            output_path
        )
    )

    if systemic_llm_failure:
        logger.error(
            'lebih dari 10%% eskalasi LLM gagal - kemungkinan masalah sistemik '
            '(bukan noise acak). File JSON di atas tetap tersimpan.'
        )
        return 3

    return 0


@click.command(help=__title__)
@click.version_option(version=__version__, prog_name=__title__)
@click.option(
    '--month',
    default=None,
    help=(
        'YYYY-MM - shorthand for --input runs/<month>/comments.json and '
        '--output runs/<month>/analysis_result.json (either can still be '
        'overridden explicitly)'
    )
)
@click.option(
    '--input', 'input_path',
    default=None,
    type=click.Path(exists=False, dir_okay=False),
    help='path to comments.json (required unless --month is given)'
)
@click.option(
    '--output', 'output_path',
    default=None,
    help='path to write analysis_result.json (required unless --month is given)'
)
@click.option(
    '--fresh',
    is_flag=True,
    default=False,
    help='ignore the checkpoint (.analyze-partial.jsonl next to --output) and reclassify everything'
)
@click.option(
    '--exclude-config',
    default=None,
    type=click.Path(exists=True, dir_okay=False),
    help='path to exclude_accounts.yaml (default: none excluded manually)'
)
@click.option(
    '--stopwords-config',
    default=None,
    type=click.Path(exists=True, dir_okay=False),
    help='path to stopwords_custom.txt (default: built-in list)'
)
@click.option(
    '--threshold-config',
    default=None,
    type=click.Path(exists=True, dir_okay=False),
    help=(
        'path to a YAML with ambiguous_confidence_threshold, from scripts/'
        'calibrate_threshold.py (required only when LLM_MODEL/LLM_API_KEY are set)'
    )
)
def main(
    month: str,
    input_path: str,
    output_path: str,
    fresh: bool,
    exclude_config: str,
    stopwords_config: str,
    threshold_config: str
) -> None:
    load_dotenv()  # populates os.environ from .env if present - never overrides a var already set

    if month:
        input_path = input_path or os.path.join('runs', month, 'comments.json')
        output_path = output_path or os.path.join('runs', month, 'analysis_result.json')

    if not input_path or not output_path:
        raise click.UsageError('--input and --output are required unless --month is given')

    if not os.path.isfile(input_path):
        raise click.UsageError('--input path %r does not exist' % input_path)

    logger.info('command: %s' % ' '.join(sys.argv))

    try:
        code: int = run_analyze(
            input_path=input_path,
            output_path=output_path,
            exclude_config=exclude_config,
            stopwords_config=stopwords_config,
            threshold_config=threshold_config,
            fresh=fresh
        )
    except InvalidInputSchemaError as error:
        logger.error(str(error))
        sys.exit(2)

    sys.exit(code)


if __name__ == '__main__':
    main()
