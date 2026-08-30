import json
import os
import sys
import uuid

from typing import Any, Dict, List

import click
import yaml

from loguru import logger

from sosmed_sentiment.errors import InvalidInputSchemaError
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
from sosmed_sentiment.sentiment.lexicon_classifier import classify, get_lexicon, DEFAULT_LEXICON_VERSION
from sosmed_sentiment.sentiment.threshold_config import load_threshold_config

__title__ = 'Sosmed Sentiment Pipeline - analyze'
__version__ = '0.1.0'


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
    lexicon_config: str,
    threshold_config: str = None
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
    lexicon = get_lexicon(lexicon_config)
    threshold_score, threshold_oov = load_threshold_config(threshold_config)

    llm_model: str = os.environ.get('LLM_MODEL', '')
    llm_base_url: str = os.environ.get('LLM_BASE_URL', '')
    llm_api_key: str = os.environ.get('LLM_API_KEY', '')
    hybrid_enabled: bool = bool(llm_model and llm_api_key)

    if not hybrid_enabled:
        logger.warning(
            'LLM_MODEL/LLM_API_KEY not set - running lexicon-only, no comment will '
            'be escalated (fill in .env before trusting ambiguous-comment results)'
        )

    for record in analyzed:
        pre = _preprocess(record['text_raw'])
        filtered_tokens = filter_stopwords(pre['tokens'], stopwords)
        stemmed = stem(filtered_tokens)

        record['emoji_found'] = pre['emoji_found']
        record['text_clean'] = pre['text_clean']
        record['tokens_stemmed'] = stemmed

        if hybrid_enabled:
            result = classify_comment(
                stemmed, record['text_raw'], lexicon,
                model=llm_model, base_url=llm_base_url or None, api_key=llm_api_key,
                threshold_score=threshold_score, threshold_oov=threshold_oov
            )
        else:
            result = classify(stemmed, lexicon, neutral_band=threshold_score)
        record.update(result)

    logger.info(
        'preprocessing+sentiment: %d komentar diklasifikasi (%s)'
        % (len(analyzed), 'hybrid' if hybrid_enabled else 'lexicon-only')
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
            'lexicon_version': DEFAULT_LEXICON_VERSION if not lexicon_config else lexicon_config,
            'llm_base_url': os.environ.get('LLM_BASE_URL', ''),
            'llm_model': os.environ.get('LLM_MODEL', ''),
            'ambiguous_threshold_score': threshold_score,
            'ambiguous_threshold_oov_ratio': threshold_oov,
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
    '--input', 'input_path',
    required=True,
    type=click.Path(exists=True, dir_okay=False),
    help='path to comments.json'
)
@click.option(
    '--output', 'output_path',
    required=True,
    help='path to write analysis_result.json'
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
    '--lexicon-config',
    default=None,
    type=click.Path(exists=True, dir_okay=False),
    help='path to a word,score lexicon CSV (default: built-in starter lexicon)'
)
@click.option(
    '--threshold-config',
    default=None,
    type=click.Path(exists=True, dir_okay=False),
    help='path to a YAML with ambiguous_threshold_score/oov_ratio (default: built-in)'
)
def main(
    input_path: str,
    output_path: str,
    exclude_config: str,
    stopwords_config: str,
    lexicon_config: str,
    threshold_config: str
) -> None:
    try:
        code: int = run_analyze(
            input_path=input_path,
            output_path=output_path,
            exclude_config=exclude_config,
            stopwords_config=stopwords_config,
            lexicon_config=lexicon_config,
            threshold_config=threshold_config
        )
    except InvalidInputSchemaError as error:
        logger.error(str(error))
        sys.exit(2)

    sys.exit(code)


if __name__ == '__main__':
    main()
