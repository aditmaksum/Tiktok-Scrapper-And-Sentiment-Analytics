import os
import sys
import click

from datetime import datetime
from loguru import logger

from tiktokcomment.runner import run_batch
from tiktokcomment.sampler import parse_quota, DEFAULT_QUOTA
from tiktokcomment.errors import ScrapeError

__title__ = 'TikTok Comment Scrapper - monthly batch'
__version__ = '3.0.0'

@click.command(help=__title__)
@click.version_option(version=__version__, prog_name=__title__)
@click.option(
    '--input', 'input_csv',
    required=True,
    type=click.Path(exists=True, dir_okay=False),
    help='CSV with the column url_or_id (or id_konten), and optionally '
         'account_type and nama_pengguna_kreator (or creator_username)'
)
@click.option(
    '--output', 'output_dir',
    default='runs',
    help='root directory for run output (default: runs)'
)
@click.option(
    '--month',
    default=None,
    help='run label used as the output folder, YYYY-MM (default: current month)'
)
@click.option(
    '--max-comments',
    default=200,
    show_default=True,
    help='cap per video, replies included'
)
@click.option(
    '--max-replies',
    default=5,
    show_default=True,
    help='cap on replies fetched per comment'
)
@click.option(
    '--keep-empty',
    is_flag=True,
    help='keep comments whose text is blank (they are dropped by default)'
)
@click.option(
    '--video-delay',
    default='7,10',
    show_default=True,
    help='seconds to wait between videos, as MIN,MAX'
)
@click.option(
    '--request-delay',
    default='1,3',
    show_default=True,
    help='seconds to wait between requests inside one video, as MIN,MAX'
)
@click.option(
    '--sample',
    default=None,
    type=int,
    help='scrape a quota-balanced sample of this many videos instead of all of them'
)
@click.option(
    '--quota',
    default=','.join(str(percent) for percent in DEFAULT_QUOTA),
    show_default=True,
    help='percent split as KOL,OFFICIAL,AFFILIATE for --sample - must add up to 100'
)
@click.option(
    '--seed',
    default=None,
    type=int,
    help='reuse a seed to reproduce an earlier --sample selection'
)
@click.option(
    '--all', 'scrape_all',
    is_flag=True,
    help='scrape every video even when the input is large (skips the size guard)'
)
@click.option(
    '--fresh',
    is_flag=True,
    help='ignore the checkpoint and scrape every row again'
)
def main(
    input_csv: str,
    output_dir: str,
    month: str,
    max_comments: int,
    max_replies: int,
    video_delay: str,
    request_delay: str,
    fresh: bool,
    keep_empty: bool,
    sample: int,
    quota: str,
    seed: int,
    scrape_all: bool
) -> None:
    month = month or datetime.now().strftime('%Y-%m')

    # Caps are checked before anything touches the network. A cap of zero
    # would otherwise scrape nothing, exit 0, and still mark every video done
    # in the checkpoint, so a corrected rerun would skip them all.
    if max_comments < 1:
        logger.error('--max-comments must be at least 1, got %d' % max_comments)
        sys.exit(1)

    if max_replies < 0:
        logger.error('--max-replies cannot be negative, got %d' % max_replies)
        sys.exit(1)

    if sample is not None and sample < 1:
        logger.error('--sample must be at least 1, got %d' % sample)
        sys.exit(1)

    try:
        video_range = _parse_range(video_delay)
        request_range = _parse_range(request_delay)
        month = _check_month(month)
        percentages = parse_quota(quota)
    except ValueError as error:
        logger.error(str(error))
        sys.exit(1)

    try:
        code: int = run_batch(
            input_csv=input_csv,
            output_dir=output_dir,
            month=month,
            max_comments=max_comments,
            max_replies=max_replies,
            video_delay=video_range,
            request_delay=request_range,
            fresh=fresh,
            keep_empty=keep_empty,
            sample=sample,
            quota=percentages,
            seed=seed,
            scrape_all=scrape_all
        )
    except ScrapeError as error:
        # The operator forwards this line to whoever maintains the scraper -
        # a stack trace would tell them nothing useful.
        logger.error(str(error))
        sys.exit(2)

    sys.exit(code)

def _parse_range(
    value: str
) -> tuple:
    parts = value.split(',')
    if len(parts) != 2:
        raise ValueError('delay must be given as MIN,MAX - got %r' % value)

    try:
        low, high = float(parts[0]), float(parts[1])
    except ValueError:
        # Without this the operator gets Python's own "could not convert
        # string to float" instead of a message naming the flag format.
        raise ValueError('delay must be two numbers as MIN,MAX - got %r' % value)

    if low < 0 or high < low:
        raise ValueError('delay range %r must have 0 <= MIN <= MAX' % value)

    return low, high

def _check_month(
    value: str
) -> str:
    """Reject a month label that would write outside the output directory."""
    # A drive label is not caught by the separator check, and os.path.join
    # drops everything before it: join(r'D:\runs', 'C:') is just 'C:', so the
    # run would write to the current directory of drive C instead of --output.
    if os.path.splitdrive(value)[0] or ':' in value:
        raise ValueError(
            '--month is a folder name, not a drive or path - got %r' % value
        )

    if os.sep in value or '/' in value or os.path.pardir in value:
        raise ValueError(
            '--month is a folder name, not a path - got %r' % value
        )

    return value

if __name__ == '__main__':
    main()
