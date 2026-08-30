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


def run_generate_report(
    input_path: str,
    output_path: str,
    template_path: str
) -> int:
    with open(input_path, encoding='utf-8') as handle:
        data: Dict[str, Any] = json.load(handle)

    try:
        if template_path:
            template_dir, template_name = os.path.split(template_path)
            html = build_report(data, template_dir=template_dir, template_name=template_name)
        else:
            html = build_report(data)
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
def main(
    input_path: str,
    output_path: str,
    template_path: str
) -> None:
    sys.exit(run_generate_report(input_path, output_path, template_path))


if __name__ == '__main__':
    main()
