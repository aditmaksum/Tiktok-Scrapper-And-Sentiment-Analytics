import re
import time
import random
import jmespath

from typing import Any, Dict, Iterator, List, Optional, Tuple
from requests import Session, Response, RequestException
from loguru import logger

from tiktokcomment.typing import Comments, Comment
from tiktokcomment.errors import BlockedError, SchemaError

USER_AGENT: str = (
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
    '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
)

# Accepts a bare id, a /video/ or /photo/ permalink, and the m.tiktok.com form.
AWEME_ID_PATTERN: re.Pattern = re.compile(r'(?:/(?:video|photo)/|^)(\d{6,})')
SHORT_URL_PATTERN: re.Pattern = re.compile(
    r'https?://(?:vt|vm)\.tiktok\.com/\S+', re.IGNORECASE
)

def parse_aweme_id(
    value: str,
    resolve_short_links: Optional[bool] = True
) -> Optional[str]:
    """Turn a bare id or any TikTok video URL into an aweme_id.

    Short links (vt/vm.tiktok.com) are resolved by following the redirect,
    which is the only way to recover the id they hide.
    Returns None when nothing usable is found, so the caller can skip the
    row instead of crashing on it.

    resolve_short_links=False makes the whole function offline. The sampler
    reads thousands of rows at once, and one HTTP HEAD per short link would
    mean thousands of requests before a single comment is scraped. Offline,
    a short link simply yields None and the caller decides what to do with it.
    """
    if not value:
        return None

    value = value.strip()

    if resolve_short_links and SHORT_URL_PATTERN.fullmatch(value):
        try:
            # A session per short link would otherwise be left open, and a
            # monthly CSV can hold hundreds of them.
            with Session() as session:
                response: Response = session.head(
                    value,
                    allow_redirects=True,
                    timeout=20,
                    headers={'User-Agent': USER_AGENT}
                )
                value = response.url
        except RequestException as error:
            logger.warning('cannot resolve short url %s (%s)' % (value, error))
            return None

    match: Optional[re.Match] = AWEME_ID_PATTERN.search(value)

    return match.group(1) if match else None

class TiktokComment:
    BASE_URL: str = 'https://www.tiktok.com'
    API_URL: str = '%s/api' % BASE_URL

    PAGE_SIZE: int = 50
    MAX_COMMENTS: int = 200
    MAX_REPLIES: int = 5

    # Hard stop on paging. The cap counts kept comments only, so a video whose
    # pages are all blank comments never reaches it and would page for as long
    # as TikTok keeps saying has_more. These bound the request budget one video
    # can spend no matter what comes back.
    MAX_PAGES: int = 40
    MAX_REPLY_PAGES: int = 5

    def __init__(
        self: 'TiktokComment',
        max_comments: Optional[int] = MAX_COMMENTS,
        max_replies: Optional[int] = MAX_REPLIES,
        request_delay: Optional[Tuple[float, float]] = (1.0, 3.0),
        max_retries: Optional[int] = 3,
        keep_empty: Optional[bool] = False
    ) -> None:
        self.__session: Session = Session()
        self.__session.headers.update({
            'User-Agent': USER_AGENT,
            'Referer': '%s/' % self.BASE_URL
        })
        self.max_comments: int = max_comments
        self.max_replies: int = max_replies
        self.request_delay: Tuple[float, float] = request_delay
        self.max_retries: int = max_retries
        self.keep_empty: bool = keep_empty
        self.aweme_id: str = ''
        self.__first_request: bool = True
        self.skipped_empty: int = 0

    def __usable(
        self: 'TiktokComment',
        raw: Dict[str, Any]
    ) -> bool:
        """Whether a raw comment carries anything worth collecting.

        Some comments come back with an empty text and nothing else: no
        image_list, status 1, not hidden. Probed on 2026-08-28, they are
        genuinely blank rather than sticker or photo comments, so there is
        nothing in them to read or to score.

        Dropping them here rather than after parsing means a blank comment
        never spends a slot of the per-video cap, and its replies are never
        fetched at all.
        """
        if self.keep_empty:
            return True

        if (raw.get('text') or '').strip():
            return True

        self.skipped_empty += 1

        return False

    def __sleep(
        self: 'TiktokComment'
    ) -> None:
        """Randomised gap between requests inside one video.

        Randomised rather than fixed so the request train does not form a
        uniform interval - a burst of evenly spaced calls is the easiest
        pattern to flag. The first request of a video does not wait; the
        batch runner already paused between videos.
        """
        if self.__first_request:
            self.__first_request = False
            return

        low, high = self.request_delay
        if high > 0:
            time.sleep(random.uniform(low, high))

    def __get(
        self: 'TiktokComment',
        path: str,
        params: Dict[str, Any]
    ) -> Dict[str, Any]:
        """One API call with pacing, retry, and block detection.

        Raises BlockedError when TikTok answers with anything that is not
        comment JSON - a non-2xx status, an empty body, or an HTML
        block/captcha page. That is the failure signature the smoke test
        looks for.
        """
        last_error: str = ''

        for attempt in range(1, self.max_retries + 1):
            self.__sleep()

            try:
                response: Response = self.__session.get(
                    '%s/%s' % (self.API_URL, path),
                    params=params,
                    timeout=30
                )
            except RequestException as error:
                last_error = 'request failed: %s' % error
                logger.warning('attempt %d/%d %s' % (attempt, self.max_retries, last_error))
                time.sleep(2 ** attempt)
                continue

            if response.status_code != 200:
                last_error = 'HTTP %d' % response.status_code
                logger.warning('attempt %d/%d %s' % (attempt, self.max_retries, last_error))
                time.sleep(2 ** attempt)
                continue

            if not response.text.strip():
                # 200 with an empty body is how TikTok answers an endpoint
                # that now requires request signing. Retrying does not help.
                raise BlockedError(
                    'TikTok returned HTTP 200 with an empty body for %s - '
                    'the endpoint now requires signed requests.' % path
                )

            try:
                return response.json()
            except ValueError:
                raise BlockedError(
                    'TikTok returned non-JSON content for %s (likely a block '
                    'or captcha page, %d bytes).' % (path, len(response.text))
                )

        raise BlockedError(
            'gave up on %s after %d attempts (%s)' % (path, self.max_retries, last_error)
        )

    def __parse_comment(
        self: 'TiktokComment',
        data: Dict[str, Any],
        with_replies: Optional[bool] = True
    ) -> Comment:
        parsed: Dict[str, Any] = jmespath.search(
            """
            {
                comment_id: cid,
                username: user.unique_id,
                nickname: user.nickname,
                comment: text,
                create_time: create_time,
                avatar: user.avatar_thumb.url_list[0],
                digg_count: digg_count,
                total_reply: reply_comment_total
            }
            """,
            data
        )

        if not parsed or not parsed.get('comment_id'):
            raise SchemaError(
                'comment object is missing its "cid" field - the TikTok '
                'response shape has changed.'
            )

        parsed['create_time'] = self.__read_create_time(parsed)
        parsed['username'] = parsed.get('username') or ''
        parsed['nickname'] = parsed.get('nickname') or ''
        parsed['comment'] = parsed.get('comment') or ''
        parsed['avatar'] = parsed.get('avatar') or ''
        parsed['total_reply'] = parsed.get('total_reply') or 0

        replies: List[Comment] = []
        if with_replies and parsed['total_reply'] and self.max_replies > 0:
            replies = list(self.get_replies(parsed['comment_id']))

        comment: Comment = Comment(**parsed, replies=replies)

        logger.info('%s - %s : %s' % (
                comment.create_time,
                comment.username,
                comment.comment
            )
        )

        return comment

    def __read_create_time(
        self: 'TiktokComment',
        parsed: Dict[str, Any]
    ) -> int:
        """create_time as a usable epoch, or SchemaError.

        Without this a missing or non-numeric create_time reaches
        datetime.fromtimestamp and raises TypeError, which run_batch does not
        catch: the batch dies mid-run and the month is never assembled.
        SchemaError is the same shape drift the parser already reports for a
        missing cid, and it costs one video instead of the whole run.
        """
        value: Any = parsed.get('create_time')

        try:
            return int(value)
        except (TypeError, ValueError):
            raise SchemaError(
                'comment %s has an unusable "create_time" (%r) - the TikTok '
                'response shape has changed.'
                % (parsed.get('comment_id'), value)
            )

    def get_replies(
        self: 'TiktokComment',
        comment_id: str
    ) -> Iterator[Comment]:
        """Replies for one comment, capped at max_replies.

        The cap matters more than completeness here: one viral comment with
        thousands of replies would otherwise spend the whole request budget
        of a video on a single thread.
        """
        collected: int = 0
        cursor: int = 0
        pages: int = 0

        while collected < self.max_replies:
            if pages >= self.MAX_REPLY_PAGES:
                logger.warning(
                    'stopped reading replies for %s after %d page(s) - kept %d'
                    % (comment_id, pages, collected)
                )
                return

            pages += 1
            size: int = min(self.PAGE_SIZE, self.max_replies - collected)

            data: Dict[str, Any] = self.__get(
                'comment/list/reply/',
                {
                    'aid': 1988,
                    'comment_id': comment_id,
                    'item_id': self.aweme_id,
                    'count': size,
                    'cursor': cursor
                }
            )

            replies: List[Dict[str, Any]] = data.get('comments') or []
            if not replies:
                break

            for reply in replies:
                if collected >= self.max_replies:
                    return
                if not self.__usable(reply):
                    continue
                yield self.__parse_comment(reply, with_replies=False)
                collected += 1

            if not data.get('has_more'):
                break

            cursor += len(replies)

    def get_comments(
        self: 'TiktokComment',
        aweme_id: str,
        size: Optional[int] = PAGE_SIZE,
        cursor: Optional[int] = 0,
        with_replies: Optional[bool] = True
    ) -> Comments:
        """One page of comments."""
        self.aweme_id = aweme_id

        data: Dict[str, Any] = self.__get(
            'comment/list/',
            {
                'aid': 1988,
                'aweme_id': aweme_id,
                'count': size,
                'cursor': cursor
            }
        )

        raw: List[Dict[str, Any]] = data.get('comments') or []

        # Caption is read from the unfiltered page: a blank comment can still
        # carry the share_info block that names the video.
        caption, video_url = self.__extract_video_info(raw, aweme_id)

        return Comments(
            caption=caption,
            video_url=video_url,
            comments=[
                self.__parse_comment(comment, with_replies=with_replies)
                for comment in raw if self.__usable(comment)
            ],
            has_more=data.get('has_more') or 0,
            aweme_id=aweme_id,
            page_size=len(raw)
        )

    def __extract_video_info(
        self: 'TiktokComment',
        raw: List[Dict[str, Any]],
        aweme_id: str
    ) -> Tuple[str, str]:
        """Caption and permalink, read from whichever comment carries them.

        The original code read share_info off comments[0] only, so a first
        comment without that block left caption and video_url empty. The
        permalink falls back to one built from the id, which is always
        correct and never depends on the response shape.
        """
        caption: str = ''
        video_url: str = ''

        for comment in raw:
            share_info: Dict[str, Any] = comment.get('share_info') or {}
            caption = caption or (share_info.get('title') or '')
            video_url = video_url or (share_info.get('url') or '')
            if caption and video_url:
                break

        return caption, video_url or '%s/video/%s' % (self.BASE_URL, aweme_id)

    def get_all_comments(
        self: 'TiktokComment',
        aweme_id: str
    ) -> Comments:
        """Every comment for a video, up to the max_comments cap.

        The cap counts replies too, so a video's total footprint stays
        predictable across a batch. Paging stops on has_more, on an empty
        page, or once the cap is reached - whichever comes first.
        """
        self.__first_request = True

        # Counted per video: the running total across a batch would read as
        # this video's number in the log line below.
        before_empty: int = self.skipped_empty

        collected: Comments = None
        cursor: int = 0
        pages: int = 0

        while True:
            if pages >= self.MAX_PAGES:
                logger.warning(
                    'stopped paging %s after %d page(s) - kept %d comment(s)'
                    % (aweme_id, pages, collected.total_collected if collected else 0)
                )
                break

            pages += 1

            page: Comments = self.get_comments(
                aweme_id=aweme_id,
                size=self.PAGE_SIZE,
                cursor=cursor
            )

            if collected is None:
                collected = page
            else:
                collected.comments.extend(page.comments)
                collected.fill_caption(page.caption)

            if collected.total_collected >= self.max_comments:
                break

            # page_size counts what the API returned, filtering aside. A page
            # of nothing but blank comments is empty after filtering but still
            # has to move the cursor, or the same page comes back forever.
            if not page.has_more or not page.page_size:
                break

            cursor += page.page_size

        self.__trim(collected)

        blank_here: int = self.skipped_empty - before_empty

        logger.info('collected %d comments (incl. replies) for %s%s' % (
            collected.total_collected,
            aweme_id,
            ', skipped %d blank' % blank_here if blank_here else ''
        ))

        return collected

    def __trim(
        self: 'TiktokComment',
        collected: Comments
    ) -> None:
        """Drop whatever overshot the cap on the last page."""
        budget: int = self.max_comments
        kept: List[Comment] = []

        for comment in collected.comments:
            if budget <= 0:
                break
            kept.append(comment)
            budget -= 1 + len(comment.replies)

        collected.comments[:] = kept

    def __call__(
        self: 'TiktokComment',
        aweme_id: str
    ) -> Comments:
        return self.get_all_comments(
            aweme_id=aweme_id
        )
