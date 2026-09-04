import json
import os
import sys

from datetime import datetime
from typing import Any, Dict, List, Optional

import click

from loguru import logger

from sosmed_sentiment.errors import ReportBuildError
from sosmed_sentiment.report import llm_insights
from sosmed_sentiment.report import insights as insights_mod
from sosmed_sentiment.report.html_builder import (
    REQUIRED_TOP_LEVEL_FIELDS, build_report, build_tier_summary
)

__title__ = 'Sosmed Sentiment Pipeline - generate_report'
__version__ = '0.1.0'


def _load_account_type_map(
    comments_json_path: str
) -> Dict[str, str]:
    """video_id -> account_type, read from the scraper's comments.json.

    analysis_result.json never carries account_type per comment (the analyze
    pipeline is deliberately left untouched), so the report reads it straight
    from the source scrape output instead. Missing or unreadable is not
    fatal - the report still renders, just without the per-account-type
    breakdown.
    """
    if not comments_json_path or not os.path.exists(comments_json_path):
        return {}

    try:
        with open(comments_json_path, encoding='utf-8') as handle:
            raw: Any = json.load(handle)
    except (OSError, ValueError) as error:
        logger.warning('cannot read %s (%s) - account_type breakdown skipped' % (
            comments_json_path, error
        ))
        return {}

    if not isinstance(raw, list):
        return {}

    return {
        str(video['aweme_id']): (video.get('account_type') or 'unknown')
        for video in raw
        if isinstance(video, dict) and video.get('aweme_id')
    }


def _print_tier_sanity_check(
    tier_rows: Any
) -> None:
    """T-ENG-9 (explicit user requirement): a plain-text, chat-postable table
    of per-tier net sentiment + video/comment counts, printed to the console
    log BEFORE the HTML file is written - so the numbers are visible in the
    terminal even when --output points somewhere the user won't immediately
    open. Prints every tier `build_tier_summary()` returns, including a
    zero-comment "Unknown" tier (depends on html_builder._tier_breakdown()'s
    D8 fix: it no longer omits an empty tier).
    """
    logger.info('Sanity check per tipe akun (sebelum menulis HTML):')
    for row in tier_rows:
        # total_count (top-level + balasan), not comment_count (top-level
        # saja) - matches the spec's per-type comment count (kol=3.621,
        # affiliate=2.798, official=2.056 on the 2026-08 run), which counts
        # every comment tied to the tier, replies included.
        logger.info('%s: net %+.1f, %d video, %d komentar' % (
            row['label'], row['net'], row['video_count'], row['total_count']
        ))


def _print_narrative_review(
    result: Dict[str, Any],
    payload: Dict[str, Any],
    review_path: str
) -> None:
    """docs/plans/2026-09-04-llm-narrative-citation-guardrail.md §6 - the
    human spot-check flag. Prints EVERY narrative sentence (headline/risk/
    actions) alongside the metrics dict numbers an operator can cross-check
    them against, mirroring _print_tier_sanity_check()'s existing
    print-to-terminal precedent. Leads with a one-line narrative-source
    banner (Decision #16/T10) BEFORE the sentence dump, so the operator
    knows on line 1 whether they're reading an LLM-verified narrative or a
    silent fallback - the one fact that most changes how skeptically they
    should read the numbers that follow.
    """
    logger.info('=== --narrative-review: sumber narasi = %s ===' % result['status'])
    if result.get('reject_reason'):
        logger.info('(alasan reject terakhir: %s)' % result['reject_reason'])

    narrative = result['narrative']
    for section in ('headline', 'risk', 'actions'):
        logger.info('--- %s ---' % section)
        for item in narrative.get(section, []):
            logger.info('[%s] %s' % (item.get('title', ''), item.get('body', '')))

    logger.info('--- angka pembanding (metrics dict yang dikirim ke LLM) ---')
    logger.info('net_overall=%s classified_total=%s sentiment_counts=%s' % (
        payload.get('net_overall'), payload.get('classified_total'), payload.get('sentiment_counts')
    ))
    for tier in payload.get('tier_breakdown', []):
        logger.info('%s: net=%s video_count=%s comment_count=%s' % (
            tier.get('label'), tier.get('net'), tier.get('video_count'), tier.get('comment_count')
        ))
    logger.info('sidecar audit: %s' % review_path)


def run_generate_report(
    input_path: str,
    output_path: str,
    template_path: str,
    comments_json_path: str = None,
    total_population_videos: int = None,
    no_narrative: bool = False,
    fresh_narrative: bool = False,
    narrative_review: bool = False
) -> int:
    with open(input_path, encoding='utf-8') as handle:
        data: Dict[str, Any] = json.load(handle)

    if comments_json_path is None:
        comments_json_path = os.path.join(os.path.dirname(input_path) or '.', 'comments.json')

    account_type_map: Dict[str, str] = _load_account_type_map(comments_json_path)
    if not account_type_map:
        logger.warning(
            '%s not found or unusable - report will skip the per-account-type '
            'breakdown' % comments_json_path
        )

    # Narrative generation needs the deterministic metrics dict + per-tier
    # rows BEFORE build_report() renders (Eng phase Section 1 diagram: the
    # LLM/fallback narrative must overwrite metrics['narrative'] before
    # html_builder.build_report() runs). build_metrics()/build_tier_summary()
    # are cheap, pure, deterministic functions at this project's comment-
    # count scale (Rules.md §9's own "kecil" framing) - computing them here
    # (and again inside build_report(), which needs its own full metrics
    # dict to render every other section) is a deliberate, documented
    # trade-off against a larger html_builder/insights refactor, not an
    # oversight.
    tier_rows: List[Dict[str, Any]] = build_tier_summary(data, account_type_map)
    schema_missing = [field for field in REQUIRED_TOP_LEVEL_FIELDS if field not in data]
    metrics_for_narrative: Optional[Dict[str, Any]] = None
    if not schema_missing:
        try:
            metrics_for_narrative = insights_mod.build_metrics(data, total_population_videos)
        except (KeyError, TypeError, ZeroDivisionError) as error:
            # Schema-valid-but-otherwise-malformed input is validated (and
            # rejected) by build_report() itself just below - if metrics
            # computation trips on something build_report()'s own _validate()
            # doesn't catch, fall through to that same error path rather
            # than crash here; the narrative section is skipped, not fatal.
            logger.warning(
                'llm_insights: metrics dict tidak bisa dihitung (%s) - narasi LLM dilewati, '
                'lanjut ke validasi standar' % error
            )
            metrics_for_narrative = None
    # schema_missing is non-empty -> build_report()'s own _validate() below
    # raises the exact same ReportBuildError this used to raise before the
    # narrative layer existed; narrative generation is skipped entirely
    # rather than attempted against input build_report() will reject anyway.

    output_dir = os.path.dirname(output_path) or '.'
    cache_path = os.path.join(output_dir, 'narrative.json')
    review_path = os.path.join(output_dir, 'narrative_review.json')

    narrative_override: Optional[Dict[str, Any]] = None
    narrative_payload: Dict[str, Any] = {}
    narrative_result: Optional[Dict[str, Any]] = None
    if metrics_for_narrative is not None:
        narrative_result = llm_insights.generate_narrative_with_guardrail(
            metrics_for_narrative, tier_rows, total_population_videos,
            cache_path=cache_path, fresh=fresh_narrative, no_narrative=no_narrative
        )
        narrative_override = narrative_result['narrative']
        narrative_payload = llm_insights.build_payload(metrics_for_narrative, tier_rows)

        generated_at = datetime.now().strftime('%Y-%m-%dT%H:%M:%S')
        sidecar_written = llm_insights.write_review_sidecar(
            review_path, narrative_result['status'], generated_at, narrative_override
        )
        if not sidecar_written:
            logger.warning('narrative_review.json tidak tertulis - laporan tetap lanjut dibuat')

    try:
        if template_path:
            template_dir, template_name = os.path.split(template_path)
            html = build_report(
                data, template_dir=template_dir, template_name=template_name,
                account_type_map=account_type_map,
                total_population_videos=total_population_videos,
                narrative_override=narrative_override
            )
        else:
            html = build_report(
                data, account_type_map=account_type_map,
                total_population_videos=total_population_videos,
                narrative_override=narrative_override
            )
    except ReportBuildError as error:
        logger.error(str(error))
        return 2

    _print_tier_sanity_check(tier_rows)

    if output_dir:
        os.makedirs(output_dir, exist_ok=True)

    with open(output_path, 'w', encoding='utf-8') as handle:
        handle.write(html)

    logger.info('wrote %s' % output_path)

    # T15/Decision #21: --no-narrative + --narrative-review defined
    # explicitly, not left to click's flag precedence - both flags can be
    # passed together, --narrative-review still prints its dump (banner
    # reads 'narrative-disabled', sentences are the deterministic fallback,
    # not silently suppressed) so the operator sees exactly what --no-
    # narrative produced instead of getting no output for a flag they
    # explicitly passed.
    if narrative_review and narrative_result is not None:
        reviewed_at = datetime.now().strftime('%Y-%m-%dT%H:%M:%S')
        reviewed_by = os.environ.get('USER') or os.environ.get('USERNAME') or 'unknown'
        _print_narrative_review(narrative_result, narrative_payload, review_path)
        llm_insights.write_review_sidecar(
            review_path, narrative_result['status'], generated_at, narrative_override,
            reviewed_at=reviewed_at, reviewed_by=reviewed_by
        )

    return 0


@click.command(help=__title__)
@click.version_option(version=__version__, prog_name=__title__)
@click.option(
    '--input', 'input_path',
    required=True,
    type=click.Path(exists=True, dir_okay=False),
    help='path to analysis_result.json'
)
@click.option(
    '--output', 'output_path',
    default=None,
    help='path to write report.html (default: report.html next to --input)'
)
@click.option(
    '--template',
    'template_path',
    default=None,
    type=click.Path(exists=True, dir_okay=False),
    help='path to a custom .html.j2 template (default: built-in template)'
)
@click.option(
    '--comments-json',
    'comments_json_path',
    default=None,
    type=click.Path(exists=True, dir_okay=False),
    help='source comments.json, for the per-account-type breakdown '
         '(default: comments.json next to --input)'
)
@click.option(
    '--total-population-videos',
    'total_population_videos',
    default=None,
    type=int,
    help='operator-supplied estimate of the account\'s TOTAL video count '
         '(not derivable from --input, which only describes the sampled '
         'videos) - enables the demoted trend caveat to state how thin the '
         'sample is relative to the real population; omitted by default'
)
@click.option(
    '--no-narrative',
    is_flag=True,
    default=False,
    help='skip the LLM narrative call entirely (report uses the deterministic '
         'narrative), even when LLM_API_KEY is configured - independent of '
         'analyze\'s own LLM sentiment escalation, which is unaffected'
)
@click.option(
    '--fresh-narrative',
    is_flag=True,
    default=False,
    help='ignore narrative.json\'s cache and force a fresh LLM narrative '
         'generation (matches --fresh\'s naming on the analyze CLI)'
)
@click.option(
    '--narrative-review',
    is_flag=True,
    default=False,
    help='after writing report.html, print every narrative sentence plus the '
         'metrics numbers it cites, for a human spot-check - recommended on '
         'every run for the first 2 weeks, then sampled ~1-in-5 (see '
         'docs/runbook.md)'
)
def main(
    input_path: str,
    output_path: str,
    template_path: str,
    comments_json_path: str,
    total_population_videos: int,
    no_narrative: bool,
    fresh_narrative: bool,
    narrative_review: bool
) -> None:
    if not output_path:
        # plan §5: the original "command too long" complaint - defaults next
        # to --input so the common case is one flag, not two.
        output_path = os.path.join(os.path.dirname(input_path) or '.', 'report.html')
    sys.exit(run_generate_report(
        input_path, output_path, template_path, comments_json_path,
        total_population_videos, no_narrative, fresh_narrative, narrative_review
    ))


if __name__ == '__main__':
    main()
