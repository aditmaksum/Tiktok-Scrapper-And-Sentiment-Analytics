import os
import csv
import json
import time
import random

from typing import Any, Dict, Iterator, List, Optional, Tuple
from datetime import datetime
from loguru import logger

from tiktokcomment import TiktokComment
from tiktokcomment.tiktokcomment import parse_aweme_id, SHORT_URL_PATTERN
from tiktokcomment.typing import Comments
from tiktokcomment.errors import ScrapeError, BlockedError, SchemaError

# The video column goes by more than one name: url_or_id is what this tool
# documents, id_konten is what the order-mirror export produces. Accepting
# both means nobody renames a column by hand every month.
VIDEO_COLUMNS: Tuple[str, ...] = ('url_or_id', 'id_konten')

# Same dual-name reasoning as VIDEO_COLUMNS: nama_pengguna_kreator is the
# order-mirror export's column, creator_username is what this tool documents.
CREATOR_COLUMN: Tuple[str, ...] = ('nama_pengguna_kreator', 'creator_username')

OPTIONAL_COLUMNS: Tuple[str, ...] = ('account_type',) + CREATOR_COLUMN

DEFAULT_ACCOUNT_TYPE: str = 'unknown'

# Above this many videos, a batch without --sample is refused. At the measured
# 54-123 seconds per video that is somewhere between 7 and 17 hours, which is
# long enough that starting it by accident costs a day. --all says you meant it.
MAX_UNSAMPLED_VIDEOS: int = 500

CSV_FIELDS: Tuple[str, ...] = (
    'account_type', 'aweme_id', 'caption', 'video_url', 'video_author_username',
    'comment_id', 'parent_comment_id', 'is_reply',
    'username', 'nickname', 'comment', 'create_time',
    'digg_count', 'total_reply'
)

# Excel and LibreOffice execute a cell that opens with one of these as a
# formula rather than showing it as text.
FORMULA_PREFIXES: Tuple[str, ...] = ('=', '+', '-', '@')

def safe_cell(
    value: Any
) -> Any:
    """Neutralise a cell a spreadsheet would otherwise run as a formula.

    Comment text comes from strangers on the internet and lands in a CSV the
    analyst opens in Excel. A comment of "=cmd|' /c calc'!A1" is a live
    formula there, not a comment. A leading apostrophe makes Excel treat the
    cell as text; nothing else about the value changes.
    """
    if isinstance(value, str) and value.startswith(FORMULA_PREFIXES):
        return "'" + value

    return value

class Row:
    """One line of the monthly input CSV, already validated."""

    def __init__(
        self: 'Row',
        line_number: int,
        aweme_id: str,
        account_type: str,
        creator_username: str = ''
    ) -> None:
        self.line_number: int = line_number
        self.aweme_id: str = aweme_id
        self.account_type: str = account_type
        self.creator_username: str = creator_username

def read_rows(
    path: str,
    resolve_short_links: Optional[bool] = True
) -> Tuple[List[Row], List[str]]:
    """Read the input CSV into rows, keeping the skipped ones as messages.

    A bad line never aborts the batch - it is reported at the end so the
    operator knows exactly which lines to fix next month.

    resolve_short_links=False keeps the read offline for the sampler, which
    scans the whole order mirror at once. Offline, a short link cannot be
    turned into an id, so the raw value is kept as the row's identity and
    passed through to the output - batch.py resolves it later, when there
    are a hundred of them rather than thousands.
    """
    rows: List[Row] = []
    skipped: List[str] = []
    account_types: Dict[str, str] = {}

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

        creator_column: Optional[str] = next(
            (column for column in CREATOR_COLUMN if column in header), None
        )

        seen: set = set()

        for line_number, raw in enumerate(reader, start=2):
            value: str = (raw.get(video_column) or '').strip()

            # Left blank on purpose is fine - losing a video to a missed cell
            # would cost more than an untidy label.
            account_type: str = (raw.get('account_type') or '').strip() or DEFAULT_ACCOUNT_TYPE

            # No column at all (older CSV) and an empty cell both mean the
            # same thing here: nothing to auto-exclude by, fall back to the
            # manual exclude-list.
            creator_username: str = (
                (raw.get(creator_column) or '').strip() if creator_column else ''
            )

            if not value:
                skipped.append(
                    'line %d: skipped - %s is empty' % (line_number, video_column)
                )
                continue

            aweme_id: Optional[str] = parse_aweme_id(
                value, resolve_short_links=resolve_short_links
            )

            if not aweme_id and not resolve_short_links                     and SHORT_URL_PATTERN.fullmatch(value):
                # Offline, a short link hides its id. Dropping the row would
                # quietly remove real videos from the sample, so the raw link
                # travels on as its own identity.
                aweme_id = value

            if not aweme_id:
                skipped.append(
                    'line %d: skipped - cannot read a video id from %r'
                    % (line_number, value)
                )
                continue

            if aweme_id in seen:
                # The order mirror carries one row per order, so the same video
                # repeats. First row wins, which only matters when the repeats
                # disagree about account_type - and that is a data problem in
                # the mirror worth saying out loud, because it moves a video
                # from one tier to another.
                if account_types[aweme_id] != account_type:
                    skipped.append(
                        'line %d: duplicate of %s carries account_type %r, '
                        'keeping %r from the earlier line'
                        % (line_number, aweme_id, account_type,
                           account_types[aweme_id])
                    )
                else:
                    skipped.append(
                        'line %d: skipped - duplicate of an earlier line (%s)'
                        % (line_number, aweme_id)
                    )
                continue

            seen.add(aweme_id)
            account_types[aweme_id] = account_type
            rows.append(Row(line_number, aweme_id, account_type, creator_username))

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

def _creator_appears(
    data: Comments,
    creator_username: str
) -> bool:
    """Whether creator_username matches any comment or reply on this video.

    Exact, case-sensitive - same rule as the manual exclude-list (FR-02),
    kept consistent on purpose. Replies are one level deep only, matching
    what the API itself returns (see typing/comment.py).
    """
    for top in data.comments:
        if top.username == creator_username:
            return True
        for reply in top.replies:
            if reply.username == creator_username:
                return True

    return False

def flatten(
    data: Dict[str, Any]
) -> Iterator[Dict[str, Any]]:
    """One CSV line per comment and per reply, ready for the analyst."""
    shared: Dict[str, Any] = {
        'account_type': data.get('account_type', DEFAULT_ACCOUNT_TYPE),
        'aweme_id': data.get('aweme_id', ''),
        'caption': data.get('caption', ''),
        'video_url': data.get('video_url', ''),
        'video_author_username': data.get('video_author_username', '')
    }

    for comment in data.get('comments') or []:
        yield {
            **shared,
            **_comment_fields(comment),
            'parent_comment_id': '',
            'is_reply': 0
        }

        for reply in comment.get('replies') or []:
            yield {
                **shared,
                **_comment_fields(reply),
                'parent_comment_id': comment.get('comment_id', ''),
                'is_reply': 1
            }

def _comment_fields(
    comment: Dict[str, Any]
) -> Dict[str, Any]:
    """The per-comment columns, read so a missing key cannot stop the write.

    A checkpoint written by an older version - or by a run that died
    mid-append - can hold a comment without every field. Indexing it directly
    raised KeyError inside _assemble, which lost the whole month's output even
    though the scraped data itself was safe in the checkpoint.
    """
    return {
        'comment_id': comment.get('comment_id', ''),
        'username': comment.get('username', ''),
        'nickname': comment.get('nickname', ''),
        'comment': comment.get('comment', ''),
        'create_time': comment.get('create_time', ''),
        'digg_count': comment.get('digg_count', 0),
        'total_reply': comment.get('total_reply', 0)
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

        # dirname is empty for a bare filename, and os.makedirs('') raises.
        directory: str = os.path.dirname(self.path)
        if directory:
            os.makedirs(directory, exist_ok=True)
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
    fresh: bool,
    keep_empty: Optional[bool] = False,
    sample: Optional[int] = None,
    quota: Optional[Tuple[int, int, int]] = None,
    seed: Optional[int] = None,
    scrape_all: Optional[bool] = False
) -> int:
    """Scrape the videos in the CSV. Returns the process exit code.

    With --sample, the order mirror can be handed straight to this command:
    the videos are picked by the tier quota first, and the chosen list is
    written next to the results so the run can be inspected and reproduced.
    """
    rows, skipped = read_rows(input_csv)

    for message in skipped:
        logger.warning(message)

    if not rows:
        logger.error('no usable rows in %s - nothing to scrape' % input_csv)
        return 1

    run_dir: str = os.path.join(output_dir, month)
    partial_path: str = os.path.join(run_dir, '.partial.jsonl')

    rows = _select_videos(
        rows=rows,
        skipped=skipped,
        input_csv=input_csv,
        run_dir=run_dir,
        sample=sample,
        quota=quota,
        seed=seed,
        scrape_all=scrape_all
    )

    if fresh and os.path.exists(partial_path):
        os.remove(partial_path)
        logger.info('--fresh: cleared previous checkpoint')

    checkpoint: Checkpoint = Checkpoint(partial_path)
    if checkpoint.done:
        logger.info('resuming - %d video(s) already done' % len(checkpoint.done))

    pending: List[Row] = [row for row in rows if not checkpoint.has(row.aweme_id)]

    if not pending:
        # Probing here would spend requests on videos that are already done,
        # and an empty probe would fail a rerun that has nothing left to do.
        logger.info('every video is already in the checkpoint - nothing to scrape')
        for path in _assemble(run_dir, checkpoint):
            logger.info('wrote %s' % path)
        return 0

    smoke_test([row.aweme_id for row in pending])

    scraper: TiktokComment = TiktokComment(
        max_comments=max_comments,
        max_replies=max_replies,
        request_delay=request_delay,
        keep_empty=keep_empty
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

        if row.creator_username and not _creator_appears(data, row.creator_username):
            # A hand-typed CSV column, unlike a scraped username, carries no
            # guarantee it matches anything - a typo here silently defeats
            # FR-11's auto-exclude with no other signal that it happened.
            # This is not necessarily wrong: a creator who never replies to
            # their own comments looks identical, so it is a nudge to check
            # manually, not proof of a mistake.
            logger.warning(
                "%s: creator_username %r never appears among this video's "
                'comments or replies - check for a typo, or the creator '
                'simply never comments on their own video'
                % (row.aweme_id, row.creator_username)
            )

        entry: Dict[str, Any] = data.dict
        entry['account_type'] = row.account_type
        entry['video_author_username'] = row.creator_username
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

def _select_videos(
    rows: List[Row],
    skipped: List[str],
    input_csv: str,
    run_dir: str,
    sample: Optional[int],
    quota: Optional[Tuple[int, int, int]],
    seed: Optional[int],
    scrape_all: Optional[bool]
) -> List[Row]:
    """Narrow the input down to the videos this run should actually scrape.

    Imported here rather than at module scope: the sampler reads its CSV
    through read_rows, so a top-level import in either direction would be a
    cycle.
    """
    from tiktokcomment import sampler

    if not sample:
        # The guard that would have caught pointing this command at the whole
        # order mirror: 5049 videos is a three-day run, and nothing about the
        # command line said so.
        if len(rows) > MAX_UNSAMPLED_VIDEOS and not scrape_all:
            raise ScrapeError(
                '%s holds %d videos, which is about %s of scraping. Pass '
                '--sample N to scrape a quota-balanced sample of them, or '
                '--all if you really mean to scrape every one.'
                % (input_csv, len(rows), sampler.estimate_duration(len(rows)))
            )

        return rows

    if seed is None:
        seed = random.SystemRandom().randrange(2 ** 32)

    # An instance, not random.seed(): the global RNG also paces the scraper's
    # requests, so seeding it globally would tie the sample to that.
    rng: random.Random = random.Random(seed)

    picked, allocation, available, unfilled = sampler.sample_rows(
        rows, sample, quota or sampler.DEFAULT_QUOTA, rng
    )

    logger.info('sampling %d of %d video(s), seed %d' % (
        len(picked), len(rows), seed
    ))
    for tier in sampler.TIER_ORDER:
        logger.info('%-10s %4d sampled of %d available' % (
            tier, allocation[tier], available[tier]
        ))

    if unfilled:
        logger.warning(
            '%d slot(s) of the requested %d could not be filled - the input '
            'does not hold enough videos' % (unfilled, sample)
        )

    logger.info('this run will take roughly %s' % (
        sampler.estimate_duration(len(picked))
    ))

    # Written before a single request goes out, so the run can be inspected
    # while it is still running and reproduced from the seed afterwards.
    manifest: Dict[str, Any] = sampler.build_manifest(
        input_csv=input_csv,
        size=sample,
        quota=quota or sampler.DEFAULT_QUOTA,
        seed=seed,
        allocation=allocation,
        available=available,
        unfilled=unfilled,
        duplicates=len(skipped),
        excluded=0,
        exclude_sources=[],
        picked=len(picked)
    )

    csv_path, manifest_path = sampler.write_sample(
        os.path.join(run_dir, 'sample.csv'), picked, manifest
    )
    logger.info('wrote %s' % csv_path)
    logger.info('wrote %s' % manifest_path)

    return picked

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
                writer.writerow({
                    field: safe_cell(value) for field, value in line.items()
                })

    return [json_path, csv_path]
