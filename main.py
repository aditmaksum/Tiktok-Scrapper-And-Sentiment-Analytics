import os
import sys
import json
import click

from loguru import logger

from tiktokcomment import TiktokComment
from tiktokcomment.tiktokcomment import parse_aweme_id
from tiktokcomment.typing import Comments
from tiktokcomment.errors import ScrapeError

__title__ = 'TikTok Comment Scrapper'
__version__ = '3.0.0'

@click.command(
    help=__title__
)
@click.version_option(
    version=__version__,
    prog_name=__title__
)
@click.option(
    '--aweme_id',
    required=True,
    help='tiktok video id or url'
)
@click.option(
    '--size', '-s',
    default=200,
    show_default=True,
    help='cap on comments to collect, replies included'
)
@click.option(
    '--max-replies',
    default=10,
    show_default=True,
    help='cap on replies fetched per comment'
)
@click.option(
    '--output', '-o',
    default='data',
    help='directory output data'
)
def main(
    aweme_id: str,
    size: int,
    max_replies: int,
    output: str
) -> None:
    video_id: str = parse_aweme_id(aweme_id)

    if not video_id:
        logger.error(
            'cannot read a video id from %r - pass an id (7418294751977327878) '
            'or a tiktok video url' % aweme_id
        )
        sys.exit(1)

    logger.info('start scrap comments %s' % video_id)

    try:
        comments: Comments = TiktokComment(
            max_comments=size,
            max_replies=max_replies
        )(aweme_id=video_id)
    except ScrapeError as error:
        logger.error(str(error))
        sys.exit(2)

    output_dir: str = output.rstrip('/\\') or 'data'
    os.makedirs(output_dir, exist_ok=True)

    final_path: str = os.path.join(output_dir, '%s.json' % video_id)

    with open(final_path, 'w', encoding='utf-8') as handle:
        json.dump(comments.dict, handle, ensure_ascii=False, indent=4)

    logger.info('save comments %s on %s' % (video_id, final_path))


if __name__ == '__main__':
    main()
