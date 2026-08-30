from collections import Counter
from typing import Any, Dict, Iterable, List, Set

from loguru import logger


def apply_exclusions(
    comments: List[Dict[str, Any]],
    exclude_list: Iterable[str]
) -> List[Dict[str, Any]]:
    """Mark FR-02 (manual list) and FR-11 (video uploader) exclusions in place.

    Matching is exact and case-sensitive for both rules - a deliberate call
    (PRD.md FR-02 kriteria matching), not an oversight: usernames scraped
    from TikTok are consistently lowercase, and the same rule is kept for
    the hand-typed FR-11 column for consistency rather than adding a second
    matching convention.

    video_uploader wins precedence when a comment matches both (Schema.md
    exclude_reason table) - it is the more certain signal, not a guess based
    on a manual list.

    Returns the same list, mutated - callers pass it straight into the next
    pipeline stage.
    """
    excluded: Set[str] = set(exclude_list)

    if not excluded:
        logger.warning('exclude-list is empty - no manual accounts excluded (FR-02)')

    manual_count: int = 0
    uploader_count: int = 0

    for record in comments:
        username: str = record['username']

        if username and username == record['video_author_username']:
            record['excluded'] = True
            record['exclude_reason'] = 'video_uploader'
            uploader_count += 1
        elif username in excluded:
            record['excluded'] = True
            record['exclude_reason'] = 'internal_account'
            manual_count += 1

    logger.info(
        'exclude: %d excluded via manual list, %d excluded as video uploader'
        % (manual_count, uploader_count)
    )

    return comments


def detect_top_accounts(
    comments: List[Dict[str, Any]],
    top_n: int = 20
) -> List[Dict[str, Any]]:
    """FR-10: top senders by raw frequency, whether excluded or not.

    Computed over the FULL flat list (before exclude filtering), not just
    what survived - the whole point is catching an internal account that
    the manual exclude-list missed, which by definition would otherwise be
    invisible in the post-exclude data.
    """
    counts: Counter = Counter(record['username'] for record in comments if record['username'])
    reasons: Dict[str, str] = {}

    for record in comments:
        username = record['username']
        if username and record['excluded'] and username not in reasons:
            reasons[username] = record['exclude_reason']

    return [
        {
            'username': username,
            'total_muncul': count,
            'alasan': reasons.get(username) or 'belum dikecualikan - cek manual'
        }
        for username, count in counts.most_common(top_n)
    ]
