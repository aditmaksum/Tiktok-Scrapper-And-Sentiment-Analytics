from typing import Any, Dict, List, Optional

from loguru import logger

from sosmed_sentiment.errors import InvalidInputSchemaError
from sosmed_sentiment.ingest.base import PlatformAdapter

REQUIRED_COMMENT_FIELDS: tuple = ('comment_id', 'username', 'comment', 'create_time')


class TiktokAdapter(PlatformAdapter):
    """Reads the tiktok-comment-scrapper export (Schema.md §2), flattens it.

    Validates before flattening a single row - Rules.md §7: a schema
    violation always stops the whole run (exit 2), never just the one video,
    because a shape drift this early can silently corrupt everything
    downstream.
    """

    def flatten(
        self: 'TiktokAdapter',
        raw: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        if not isinstance(raw, list):
            raise InvalidInputSchemaError(
                'comments.json must be a JSON array at the root, got %s'
                % type(raw).__name__
            )

        flat: List[Dict[str, Any]] = []

        for video in raw:
            aweme_id, comments = self._validate_video(video)
            caption: str = video.get('caption') or ''
            video_author_username: str = video.get('video_author_username') or ''

            for comment in comments:
                flat.append(self._flat_record(
                    comment, aweme_id, caption, video_author_username,
                    is_reply=False, parent_comment_id=None
                ))

                for reply in comment.get('replies') or []:
                    self._validate_comment(reply, aweme_id)
                    flat.append(self._flat_record(
                        reply, aweme_id, caption, video_author_username,
                        is_reply=True, parent_comment_id=comment.get('comment_id')
                    ))

        return flat

    def _validate_video(
        self: 'TiktokAdapter',
        video: Dict[str, Any]
    ) -> tuple:
        aweme_id: Optional[Any] = video.get('aweme_id')
        comments: Optional[Any] = video.get('comments')

        if not aweme_id:
            raise InvalidInputSchemaError(
                "video missing required field 'aweme_id': %r" % video
            )

        if comments is None:
            raise InvalidInputSchemaError(
                "video aweme_id=%r missing required field 'comments' "
                '(use an empty array if the video genuinely has none)'
                % aweme_id
            )

        if not isinstance(comments, list):
            raise InvalidInputSchemaError(
                "video aweme_id=%r field 'comments' must be an array, got %s"
                % (aweme_id, type(comments).__name__)
            )

        for comment in comments:
            self._validate_comment(comment, aweme_id)

        return aweme_id, comments

    def _validate_comment(
        self: 'TiktokAdapter',
        comment: Dict[str, Any],
        aweme_id: Any
    ) -> None:
        missing: List[str] = [
            field for field in REQUIRED_COMMENT_FIELDS
            if field not in comment
        ]

        if missing:
            raise InvalidInputSchemaError(
                'video aweme_id=%r comment_id=%r missing required field(s): %s'
                % (aweme_id, comment.get('comment_id', '???'), ', '.join(missing))
            )

        replies: Any = comment.get('replies')
        if replies:
            for reply in replies:
                if reply.get('replies'):
                    # Schema.md §2: replies are one level deep only. A nested
                    # reply is a real deviation from the documented input
                    # contract, worth stopping for rather than silently
                    # flattening deeper than the schema promises.
                    raise InvalidInputSchemaError(
                        'video aweme_id=%r comment_id=%r has a nested reply '
                        "beyond one level - the input schema doesn't allow "
                        'this, confirm with the analyst before proceeding'
                        % (aweme_id, comment.get('comment_id'))
                    )

    def _flat_record(
        self: 'TiktokAdapter',
        comment: Dict[str, Any],
        video_id: Any,
        video_caption: str,
        video_author_username: str,
        is_reply: bool,
        parent_comment_id: Optional[Any]
    ) -> Dict[str, Any]:
        return {
            'comment_id': comment.get('comment_id'),
            'video_id': video_id,
            'video_caption': video_caption,
            'video_author_username': video_author_username,
            'is_reply': is_reply,
            'parent_comment_id': parent_comment_id,
            'username': comment.get('username') or '',
            'text_raw': comment.get('comment') or '',
            'create_time': comment.get('create_time') or '',
            'digg_count': comment.get('digg_count') or 0,
            'excluded': False,
            'exclude_reason': None
        }


def flatten_input(
    raw: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """Module-level convenience so callers don't need to instantiate the class."""
    total: int = len(raw) if isinstance(raw, list) else 0
    flat: List[Dict[str, Any]] = TiktokAdapter().flatten(raw)

    logger.info('ingest: %d video(s) -> %d comment(s)+reply(ies)' % (total, len(flat)))

    return flat
