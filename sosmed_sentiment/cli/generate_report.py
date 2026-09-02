import json
import os
import sys

from typing import Any, Dict

import click

from loguru import logger

from sosmed_sentiment.errors import ReportBuildError
from sosmed_sentiment.report.html_builder import build_report

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


def run_generate_report(
    input_path: str,
    output_path: str,
    template_path: str,
    comments_json_path: str = None
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

    try:
        if template_path:
            template_dir, template_name = os.path.split(template_path)
            html = build_report(
                data, template_dir=template_dir, template_name=template_name,
                account_type_map=account_type_map
            )
        else:
            html = build_report(data, account_type_map=account_type_map)
    except ReportBuildError as error:
        logger.error(str(error))
        return 2

    output_dir = os.path.dirname(output_path)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)

    with open(output_path, 'w', encoding='utf-8') as handle:
        handle.write(html)

    logger.info('wrote %s' % output_path)

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
    required=True,
    help='path to write report.html'
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
def main(
    input_path: str,
    output_path: str,
    template_path: str,
    comments_json_path: str
) -> None:
    sys.exit(run_generate_report(input_path, output_path, template_path, comments_json_path))


if __name__ == '__main__':
    main()
