import os
import csv
import json
import time
import random

from typing import Any, Dict, Iterator, List, Optional, Tuple
from datetime import datetime
from loguru import logger

from tiktokcomment import TiktokComment
from tiktokcomment.tiktokcomment import parse_aweme_id
from tiktokcomment.typing import Comments
from tiktokcomment.errors import ScrapeError, BlockedError, SchemaError

# The video column goes by more than one name: url_or_id is what this tool
# documents, id_konten is what the order-mirror export produces. Accepting
# both means nobody renames a column by hand every month.
VIDEO_COLUMNS: Tuple[str, ...] = ('url_or_id', 'id_konten')
OPTIONAL_COLUMNS: Tuple[str, ...] = ('account_type',)

DEFAULT_ACCOUNT_TYPE: str = 'unknown'

CSV_FIELDS: Tuple[str, ...] = (
    'account_type', 'aweme_id', 'caption', 'video_url',
    'comment_id', 'parent_comment_id', 'is_reply',
    'username', 'nickname', 'comment', 'create_time',
    'digg_count', 'total_reply'
)

class Row:
    """One line of the monthly input CSV, already validated."""

    def __init__(
        self: 'Row',
        line_number: int,
        aweme_id: str,
        account_type: str
    ) -> None:
        self.line_number: int = line_number
        self.aweme_id: str = aweme_id
        self.account_type: str = account_type

def read_rows(
    path: str
) -> Tuple[List[Row], List[str]]:
    """Read the input CSV into rows, keeping the skipped ones as messages.

    A bad line never aborts the batch - it is reported at the end so the
    operator knows exactly which lines to fix next month.
    """
    rows: List[Row] = []
    skipped: List[str] = []

    with open(path, newline='', encoding='utf-8-sig') as handle:
        reader: csv.DictReader = csv.DictReader(handle)

        header: List[str] = list(reader.fieldnames or [])
        video_column: Optional[str] = next(
            (column for column in VIDEO_COLUMNS if column in header), None
        )

        if not video_column:
            raise ScrapeError(
                'input CSV has no video column. Expected one of: %s (plus an '
                'optional %s). Found: %s'
                % (
                    ' or '.join(VIDEO_COLUMNS),
                    ', '.join(OPTIONAL_COLUMNS),
                    ', '.join(header) or '(no header)'
                )
            )

        logger.info('reading video ids from the %r column' % video_column)

        seen: set = set()

        for line_number, raw in enumerate(reader, start=2):
            value: str = (raw.get(video_column) or '').strip()

            # Left blank on purpose is fine - losing a video to a missed cell
            # would cost more than an untidy label.
            account_type: str = (raw.get('account_type') or '').strip() or DEFAULT_ACCOUNT_TYPE

            if not value:
                skipped.append(
                    'line %d: skipped - %s is empty' % (line_number, video_column)
                )
                continue

            aweme_id: Optional[str] = parse_aweme_id(value)
            if not aweme_id:
                skipped.append(
                    'line %d: skipped - cannot read a video id from %r'
                    % (line_number, value)
                )
                continue

            if aweme_id in seen:
                skipped.append(
                    'line %d: skipped - duplicate of an earlier line (%s)'
                    % (line_number, aweme_id)
                )
                continue

            seen.add(aweme_id)
            rows.append(Row(line_number, aweme_id, account_type))

    return rows, skipped

SMOKE_TEST_VIDEOS: int = 5

def smoke_test(
    aweme_ids: List[str]
) -> None:
    """Probe a few videos with tiny requests before committing to a batch.

    Several videos rather than one, because a video with its comments turned
    off is normal: 2 of the 11 videos in the first real batch came back empty
    with a valid response. Failing on the first one would block a healthy run
    whenever that video happened to be first in the CSV.

    One empty video proves nothing. Every probe coming back empty is the
    signal worth stopping for.
    """
    probes: List[str] = aweme_ids[:SMOKE_TEST_VIDEOS]

    logger.info('smoke test on %d video(s)' % len(probes))

    probe: TiktokComment = TiktokComment(
        max_comments=3,
        max_replies=0,
        request_delay=(1.0, 2.0)
    )

    # Caption is deliberately not checked. Measured on 2026-08-28, the
    # share_info block came back on only 10 of 16 identical requests, so a
    # missing caption says nothing about whether the endpoint still works.
    # Schema drift is caught by the comment parser instead, which raises
    # SchemaError when a comment has no cid.
    empty: List[str] = []

    for aweme_id in probes:
        # BlockedError covers non-2xx, empty body, and non-JSON responses,
        # and is raised straight through: that one really is the endpoint
        # refusing to answer.
        page: Comments = probe.get_comments(
            aweme_id=aweme_id,
            size=3,
            with_replies=False
        )

        if page.comments:
            logger.info('smoke test passed on %s (%d comments)' % (
                aweme_id, len(page.comments)
            ))
            return

        empty.append(aweme_id)

    raise SchemaError(
        'smoke test found no comments on any of %d video(s): %s. Either every '
        'one of them has comments turned off, or the response shape changed.'
        % (len(empty), ', '.join(empty))
    )

def flatten(
    data: Dict[str, Any]
) -> Iterator[Dict[str, Any]]:
    """One CSV line per comment and per reply, ready for the analyst."""
    shared: Dict[str, Any] = {
        'account_type': data.get('account_type', DEFAULT_ACCOUNT_TYPE),
        'aweme_id': data.get('aweme_id', ''),
        'caption': data.get('caption', ''),
        'video_url': data.get('video_url', '')
    }

    for comment in data.get('comments') or []:
        yield {
            **shared,
            'comment_id': comment['comment_id'],
            'parent_comment_id': '',
            'is_reply': 0,
            'username': comment['username'],
            'nickname': comment['nickname'],
            'comment': comment['comment'],
            'create_time': comment['create_time'],
            'digg_count': comment['digg_count'],
            'total_reply': comment['total_reply']
        }

        for reply in comment.get('replies') or []:
            yield {
                **shared,
                'comment_id': reply['comment_id'],
                'parent_comment_id': comment['comment_id'],
                'is_reply': 1,
                'username': reply['username'],
                'nickname': reply['nickname'],
                'comment': reply['comment'],
                'create_time': reply['create_time'],
                'digg_count': reply['digg_count'],
                'total_reply': reply['total_reply']
            }

class Checkpoint:
    """Per-video results appended as they finish, so a run can resume.

    The partial file is the checkpoint: whatever is already in it has been
    scraped, so a batch that dies at video 700 restarts at 701 instead of 1.
    """

    def __init__(
        self: 'Checkpoint',
        path: str
    ) -> None:
        self.path: str = path
        self.done: Dict[str, Dict[str, Any]] = {}

        if not os.path.exists(path):
            return

        dropped: int = 0

        with open(path, encoding='utf-8') as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue

                try:
                    entry: Dict[str, Any] = json.loads(line)
                except ValueError:
                    dropped += 1
                    continue

                # A half-written line (power cut, killed mid-append) would
                # otherwise reach the final output as a record with no
                # comments field, which breaks whatever reads it next.
                if not isinstance(entry, dict) \
                        or not entry.get('aweme_id') \
                        or not isinstance(entry.get('comments'), list):
                    dropped += 1
                    continue

                self.done[entry['aweme_id']] = entry

        if dropped:
            logger.warning(
                '%d unreadable line(s) in %s were ignored - those videos will '
                'be scraped again' % (dropped, path)
            )

    def has(
        self: 'Checkpoint',
        aweme_id: str
    ) -> bool:
        return aweme_id in self.done

    def add(
        self: 'Checkpoint',
        entry: Dict[str, Any]
    ) -> None:
        self.done[entry.get('aweme_id')] = entry

        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, 'a', encoding='utf-8') as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + '\n')

    def entries(
        self: 'Checkpoint'
    ) -> List[Dict[str, Any]]:
        return list(self.done.values())

def run_batch(
    input_csv: str,
    output_dir: str,
    month: str,
    max_comments: int,
    max_replies: int,
    video_delay: Tuple[float, float],
    request_delay: Tuple[float, float],
    fresh: bool
) -> int:
    """Scrape every video in the CSV. Returns the process exit code."""
    rows, skipped = read_rows(input_csv)

    for message in skipped:
        logger.warning(message)

    if not rows:
        logger.error('no usable rows in %s - nothing to scrape' % input_csv)
        return 1

    run_dir: str = os.path.join(output_dir, month)
    partial_path: str = os.path.join(run_dir, '.partial.jsonl')

    if fresh and os.path.exists(partial_path):
        os.remove(partial_path)
        logger.info('--fresh: cleared previous checkpoint')

    checkpoint: Checkpoint = Checkpoint(partial_path)
    if checkpoint.done:
        logger.info('resuming - %d video(s) already done' % len(checkpoint.done))

    smoke_test([row.aweme_id for row in rows])

    scraper: TiktokComment = TiktokComment(
        max_comments=max_comments,
        max_replies=max_replies,
        request_delay=request_delay
    )

    failures: List[str] = []
    scraped: int = 0

    for index, row in enumerate(rows, start=1):
        if checkpoint.has(row.aweme_id):
            logger.info('[%d/%d] skip %s - already in checkpoint' % (
                index, len(rows), row.aweme_id
            ))
            continue

        if scraped:
            low, high = video_delay
            if high > 0:
                pause: float = random.uniform(low, high)
                logger.info('waiting %.1fs before next video' % pause)
                time.sleep(pause)

        logger.info('[%d/%d] scraping %s (%s)' % (
            index, len(rows), row.aweme_id, row.account_type
        ))

        try:
            data: Comments = scraper(row.aweme_id)
        except BlockedError as error:
            # A block is not one bad video - it means the endpoint stopped
            # answering, so continuing would only deepen the hole.
            logger.error('blocked while scraping %s: %s' % (row.aweme_id, error))
            logger.error(
                'stopping the batch. %d video(s) are saved in the checkpoint; '
                'rerun the same command later to continue where it stopped.'
                % len(checkpoint.done)
            )
            _assemble(run_dir, checkpoint)
            return 2
        except ScrapeError as error:
            failures.append('%s: %s' % (row.aweme_id, error))
            logger.error('failed %s: %s' % (row.aweme_id, error))
            continue

        if not data.comments:
            # Usually a wrong id rather than a video nobody commented on,
            # so say it out loud instead of writing a silent empty record.
            logger.warning(
                'line %d: %s returned no comments - check the id is right'
                % (row.line_number, row.aweme_id)
            )

        entry: Dict[str, Any] = data.dict
        entry['account_type'] = row.account_type
        entry['scraped_at'] = datetime.now().strftime('%Y-%m-%dT%H:%M:%S')

        checkpoint.add(entry)
        scraped += 1

    written: List[str] = _assemble(run_dir, checkpoint)

    logger.info('done - %d video(s) scraped this run, %d total in %s' % (
        scraped, len(checkpoint.done), run_dir
    ))
    for path in written:
        logger.info('wrote %s' % path)

    if skipped:
        logger.warning('%d CSV line(s) skipped - see warnings above' % len(skipped))
    if failures:
        logger.warning('%d video(s) failed: %s' % (len(failures), '; '.join(failures)))
        return 1

    return 0

def _assemble(
    run_dir: str,
    checkpoint: Checkpoint
) -> List[str]:
    """Write the month as one JSON and one CSV, overwriting a previous run.

    Everything lands in a single pair of files with account_type as a column,
    so filtering or grouping stays the analyst's call rather than being baked
    into the file layout.
    """
    entries: List[Dict[str, Any]] = checkpoint.entries()

    os.makedirs(run_dir, exist_ok=True)

    json_path: str = os.path.join(run_dir, 'comments.json')
    with open(json_path, 'w', encoding='utf-8') as handle:
        json.dump(entries, handle, ensure_ascii=False, indent=2)

    csv_path: str = os.path.join(run_dir, 'comments.csv')
    with open(csv_path, 'w', newline='', encoding='utf-8-sig') as handle:
        writer: csv.DictWriter = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for entry in entries:
            for line in flatten(entry):
                writer.writerow(line)

    return [json_path, csv_path]
