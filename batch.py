import sys
import click

from datetime import datetime
from loguru import logger

from tiktokcomment.runner import run_batch
from tiktokcomment.errors import ScrapeError

__title__ = 'TikTok Comment Scrapper - monthly batch'
__version__ = '3.0.0'

@click.command(help=__title__)
@click.version_option(version=__version__, prog_name=__title__)
@click.option(
    '--input', 'input_csv',
    required=True,
    type=click.Path(exists=True, dir_okay=False),
    help='CSV with the column url_or_id, and optionally account_type'
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
    default=10,
    show_default=True,
    help='cap on replies fetched per comment'
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
    fresh: bool
) -> None:
    month = month or datetime.now().strftime('%Y-%m')

    try:
        video_range = _parse_range(video_delay)
        request_range = _parse_range(request_delay)
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
            fresh=fresh
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

    low, high = float(parts[0]), float(parts[1])
    if low < 0 or high < low:
        raise ValueError('delay range %r must have 0 <= MIN <= MAX' % value)

    return low, high

if __name__ == '__main__':
    main()
