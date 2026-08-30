import os
import sys
import click

from datetime import datetime
from loguru import logger

from tiktokcomment.sampler import run_sample, parse_quota, DEFAULT_QUOTA
from tiktokcomment.errors import ScrapeError

__title__ = 'TikTok Comment Scrapper - monthly sampler'
__version__ = '3.0.0'

@click.command(help=__title__)
@click.version_option(version=__version__, prog_name=__title__)
@click.option(
    '--input', 'input_csv',
    required=True,
    type=click.Path(exists=True, dir_okay=False),
    help='order mirror CSV, with the column id_konten or url_or_id'
)
@click.option(
    '--output', 'output_csv',
    default=None,
    help='where to write the sample (default: runs/YYYY-MM/sample.csv)'
)
@click.option(
    '--size', '-s',
    default=150,
    show_default=True,
    help='how many videos to sample'
)
@click.option(
    '--quota',
    default=','.join(str(percent) for percent in DEFAULT_QUOTA),
    show_default=True,
    help='percent split as KOL,OFFICIAL,AFFILIATE - must add up to 100'
)
@click.option(
    '--seed',
    default=None,
    type=int,
    help='reuse a seed to reproduce an earlier sample (default: random, recorded)'
)
@click.option(
    '--exclude',
    multiple=True,
    help='glob of earlier results whose videos to skip, e.g. runs/*/comments.json'
)
@click.option(
    '--dry-run',
    is_flag=True,
    help='print the tier split and the batch duration estimate, write nothing'
)
def main(
    input_csv: str,
    output_csv: str,
    size: int,
    quota: str,
    seed: int,
    exclude: tuple,
    dry_run: bool
) -> None:
    # Checked before the file is opened. A size of zero would otherwise write an
    # empty sample and exit 0, which every script reads as success - the same
    # shape as ISSUE-001 in the 2026-08-28 QA report.
    if size < 1:
        logger.error('--size must be at least 1, got %d' % size)
        sys.exit(1)

    try:
        percentages = parse_quota(quota)
    except ValueError as error:
        logger.error(str(error))
        sys.exit(1)

    if output_csv is None:
        # The same path batch.py --sample writes to, so a sample always lives
        # in the run folder it belongs to - one rule, one place to look. runs/
        # is already covered by .gitignore, and the sample carries internal
        # content ids that do not belong in a commit.
        output_csv = os.path.join(
            'runs', datetime.now().strftime('%Y-%m'), 'sample.csv'
        )

    try:
        code: int = run_sample(
            input_csv=input_csv,
            output_csv=output_csv,
            size=size,
            quota=percentages,
            seed=seed,
            exclude=exclude,
            dry_run=dry_run
        )
    except ScrapeError as error:
        # One line the operator can forward as-is. A traceback would tell
        # whoever maintains this nothing useful.
        logger.error(str(error))
        sys.exit(2)

    sys.exit(code)


if __name__ == '__main__':
    main()
