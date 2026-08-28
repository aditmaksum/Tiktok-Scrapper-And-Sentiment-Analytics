import json

from typing import List, Any, Dict, Optional

from .comment import Comment

class Comments:
    def __init__(
        self: 'Comments',
        caption: str,
        video_url: str,
        comments: List[Comment],
        has_more: int,
        aweme_id: Optional[str] = None,
        page_size: Optional[int] = None
    ) -> None:
        self._caption: str = caption or ''
        self._video_url: str = video_url or ''
        self._comments: List[Comment] = comments
        self._has_more: int = has_more
        self._aweme_id: str = aweme_id or ''
        # How many comments the API actually returned, before any were
        # filtered out. The cursor has to advance by this, not by the number
        # kept, or a filtered page would be requested again.
        self._page_size: int = page_size if page_size is not None else len(comments)

    @property
    def caption(
        self: 'Comments'
    ) -> str:
        return self._caption

    def fill_caption(
        self: 'Comments',
        caption: str
    ) -> None:
        """Take a caption from a later page if this one came back without.

        TikTok returns the share_info block inconsistently, so the caption
        is whatever the first page that carries it says.
        """
        if caption and not self._caption:
            self._caption = caption

    @property
    def video_url(
        self: 'Comments'
    ) -> str:
        return self._video_url

    @property
    def comments(
        self: 'Comments'
    ) -> List[Comment]:
        return self._comments

    @property
    def has_more(
        self: 'Comments'
    ) -> int:
        return self._has_more

    @property
    def aweme_id(
        self: 'Comments'
    ) -> str:
        return self._aweme_id

    @property
    def page_size(
        self: 'Comments'
    ) -> int:
        return self._page_size

    @property
    def total_collected(
        self: 'Comments'
    ) -> int:
        """Comments plus replies - the number the 200-per-video cap counts."""
        return sum(1 + len(comment.replies) for comment in self._comments)

    @property
    def dict(
        self: 'Comments'
    ) -> Dict[str, Any]:
        return {
            'aweme_id': self._aweme_id,
            'caption': self._caption,
            'video_url': self._video_url,
            'total_collected': self.total_collected,
            'comments': [comment.dict for comment in self._comments],
            'has_more': self._has_more
        }

    @property
    def json(
        self: 'Comments'
    ) -> str:
        return json.dumps(self.dict, ensure_ascii=False)

    def __str__(
        self: 'Comments'
    ) -> str:
        return self.json
