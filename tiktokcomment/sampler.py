import os
import csv
import glob
import json
import random

from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple
from datetime import datetime
from loguru import logger

from tiktokcomment.runner import Row, read_rows, safe_cell
from tiktokcomment.errors import ScrapeError

# Tiers in priority order. The order is the contract: quota is allocated down
# this list, and unfilled slots spill down it too.
TIER_ORDER: Tuple[str, ...] = ('kol', 'official', 'affiliate', 'unknown')

# account_type is free text out of the order database ('kol account',
# 'affiliate account'), so tiers are matched by substring rather than equality.
# A value matching more than one keyword lands in the highest tier it matches.
TIER_KEYWORDS: Dict[str, Tuple[str, ...]] = {
    'kol': ('kol',),
    'official': ('official',),
    'affiliate': ('affiliate',)
}

# KOL, official, affiliate. Affiliate holds a floor rather than taking whatever
# is left: without it, a month where KOL and official fill the quota gives
# affiliate zero rows, and next month's affiliate number has nothing to compare
# against.
DEFAULT_QUOTA: Tuple[int, int, int] = (50, 30, 20)

# Measured over the 2026-08 batch: 11 videos in 20m26s, including the 7-10s gap
# between videos and the reply requests inside each one.
SECONDS_PER_VIDEO: int = 123

CSV_FIELDS: Tuple[str, ...] = ('url_or_id', 'account_type', 'creator_username')

def classify_tier(
    account_type: str
) -> str:
    """Which tier an account_type belongs to.

    Matching is casefolded and by substring because the column is free text.
    The first tier in TIER_ORDER that matches wins, so 'kol official' is a KOL
    video rather than an official one - the higher tier is the one worth
    guaranteeing.
    """
    value: str = (account_type or '').casefold()

    for tier in TIER_ORDER:
        for keyword in TIER_KEYWORDS.get(tier, ()):
            if keyword in value:
                return tier

    return 'unknown'

def parse_quota(
    value: str
) -> Tuple[int, int, int]:
    """Read the --quota flag as three percentages for KOL, official, affiliate."""
    parts: List[str] = [part.strip() for part in value.split(',')]

    if len(parts) != 3:
        raise ValueError(
            '--quota needs three percentages as KOL,OFFICIAL,AFFILIATE - got %r'
            % value
        )

    try:
        numbers: List[int] = [int(part) for part in parts]
    except ValueError:
        # Without this the operator gets Python's own "invalid literal for
        # int()" instead of a message naming the flag format.
        raise ValueError(
            '--quota needs three whole numbers as KOL,OFFICIAL,AFFILIATE - got %r'
            % value
        )

    if any(number < 0 for number in numbers):
        raise ValueError('--quota cannot contain a negative percentage - got %r' % value)

    if sum(numbers) != 100:
        raise ValueError(
            '--quota must add up to 100, %r adds up to %d' % (value, sum(numbers))
        )

    return numbers[0], numbers[1], numbers[2]

def allocate_quota(
    size: int,
    quota: Sequence[int],
    available: Dict[str, int]
) -> Tuple[Dict[str, int], int]:
    """Turn percentages into whole slots per tier, then fit them to what exists.

    Two rules do the work:

    Largest remainder. floor() first, then hand the leftover slots to the
    largest fractions, ties going to the higher tier. The total always comes
    to exactly `size` - 151 at 50/30/20 is 76/45/30, never 150 or 152.

    Spillover flows down. A tier that cannot fill its slots passes them to the
    next tier in TIER_ORDER, so affiliate may exceed its 20% when there are
    not enough KOL videos to go around. A full sample is worth more than a
    pure ratio; the manifest records what actually happened.

    Returns the per-tier allocation and the number of slots nothing could fill.
    """
    quota_tiers: Tuple[str, ...] = TIER_ORDER[:len(quota)]

    exact: Dict[str, float] = {
        tier: size * percent / 100.0
        for tier, percent in zip(quota_tiers, quota)
    }

    allocation: Dict[str, int] = {tier: 0 for tier in TIER_ORDER}
    for tier in quota_tiers:
        allocation[tier] = int(exact[tier])

    leftover: int = size - sum(allocation.values())
    ranked: List[str] = sorted(
        quota_tiers,
        key=lambda tier: (-(exact[tier] - int(exact[tier])), TIER_ORDER.index(tier))
    )
    for tier in ranked[:leftover]:
        allocation[tier] += 1

    spill: int = 0
    for tier in TIER_ORDER:
        wanted: int = allocation[tier] + spill
        taken: int = min(wanted, available.get(tier, 0))
        allocation[tier] = taken
        spill = wanted - taken

    return allocation, spill

def sample_rows(
    rows: List[Row],
    size: int,
    quota: Sequence[int],
    rng: random.Random
) -> Tuple[List[Row], Dict[str, int], Dict[str, int], int]:
    """Pick the month's videos. Returns rows, allocation, available, unfilled."""
    buckets: Dict[str, List[Row]] = {tier: [] for tier in TIER_ORDER}

    for row in rows:
        buckets[classify_tier(row.account_type)].append(row)

    available: Dict[str, int] = {tier: len(buckets[tier]) for tier in TIER_ORDER}
    allocation, unfilled = allocate_quota(size, quota, available)

    picked: List[Row] = []
    for tier in TIER_ORDER:
        picked.extend(rng.sample(buckets[tier], allocation[tier]))

    # Shuffled, not grouped by tier. A batch runs for hours and gets
    # interrupted; grouped output means a run that dies at 40% collected only
    # KOL videos. Shuffled, whatever finished is still a fair slice.
    rng.shuffle(picked)

    return picked, allocation, available, unfilled

def load_exclusions(
    patterns: Iterable[str]
) -> Tuple[set, List[str]]:
    """Video ids already scraped in earlier runs, read from runs/*/comments.json.

    Scraped, not sampled: a video that was picked last month but failed to
    scrape has no data yet and deserves another turn.
    """
    excluded: set = set()
    sources: List[str] = []

    for pattern in patterns:
        matches: List[str] = sorted(glob.glob(pattern))

        if not matches:
            logger.warning('--exclude %r matched no files' % pattern)
            continue

        for path in matches:
            try:
                with open(path, encoding='utf-8') as handle:
                    entries: Any = json.load(handle)
            except (OSError, ValueError) as error:
                # One unreadable month must not cost the whole run - the worst
                # case is scraping a few videos twice.
                logger.warning('cannot read %s (%s) - ignoring it' % (path, error))
                continue

            if not isinstance(entries, list):
                logger.warning('%s is not a list of videos - ignoring it' % path)
                continue

            before: int = len(excluded)
            for entry in entries:
                if isinstance(entry, dict) and entry.get('aweme_id'):
                    excluded.add(str(entry['aweme_id']))

            sources.append('%s (%d)' % (path, len(excluded) - before))

    return excluded, sources

def estimate_duration(
    videos: int
) -> str:
    """Rough wall-clock for scraping this many videos, in the operator's terms."""
    seconds: int = videos * SECONDS_PER_VIDEO
    hours: int = seconds // 3600
    minutes: int = (seconds % 3600) // 60

    if hours:
        return '%dh %dm' % (hours, minutes)

    return '%dm' % minutes

def build_manifest(
    input_csv: str,
    size: int,
    quota: Sequence[int],
    seed: int,
    allocation: Dict[str, int],
    available: Dict[str, int],
    unfilled: int,
    duplicates: int,
    excluded: int,
    exclude_sources: List[str],
    picked: int
) -> Dict[str, Any]:
    """The record that answers 'why these videos' three months from now."""
    return {
        'generated_at': datetime.now().strftime('%Y-%m-%dT%H:%M:%S'),
        'input': os.path.basename(input_csv),
        'requested_size': size,
        'sampled': picked,
        'seed': seed,
        'quota_percent': {
            tier: percent for tier, percent in zip(TIER_ORDER, quota)
        },
        'available_per_tier': available,
        'sampled_per_tier': allocation,
        'unfilled_slots': unfilled,
        'duplicate_rows_dropped': duplicates,
        'excluded_already_scraped': excluded,
        'exclude_sources': exclude_sources,
        'estimated_batch_duration': estimate_duration(picked)
    }

def write_sample(
    output_csv: str,
    rows: List[Row],
    manifest: Dict[str, Any]
) -> Tuple[str, str]:
    """Write the sample CSV and its manifest. Returns both paths."""
    # Checked rather than caught: Windows raises PermissionError for a
    # directory, not IsADirectoryError, so the caught message would blame
    # permissions for what is really the wrong kind of path.
    if os.path.isdir(output_csv):
        raise ScrapeError(
            '--output must be a file, not a directory - got %r' % output_csv
        )

    directory: str = os.path.dirname(output_csv)
    if directory:
        try:
            os.makedirs(directory, exist_ok=True)
        except OSError as error:
            raise ScrapeError('cannot create %s (%s)' % (directory, error))

    try:
        with open(output_csv, 'w', newline='', encoding='utf-8-sig') as handle:
            writer: csv.DictWriter = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
            writer.writeheader()
            for row in rows:
                writer.writerow({
                    'url_or_id': safe_cell(row.aweme_id),
                    'account_type': safe_cell(row.account_type),
                    'creator_username': safe_cell(row.creator_username)
                })
    except OSError as error:
        raise ScrapeError('cannot write %s (%s)' % (output_csv, error))

    manifest_path: str = os.path.splitext(output_csv)[0] + '.manifest.json'

    try:
        with open(manifest_path, 'w', encoding='utf-8') as handle:
            json.dump(manifest, handle, ensure_ascii=False, indent=2)
    except OSError as error:
        raise ScrapeError('cannot write %s (%s)' % (manifest_path, error))

    return output_csv, manifest_path

def read_candidates(
    input_csv: str
) -> Tuple[List[Row], List[str]]:
    """Every unique video in the order mirror, read offline."""
    try:
        return read_rows(input_csv, resolve_short_links=False)
    except UnicodeDecodeError:
        raise ScrapeError(
            '%s is not UTF-8 text - re-export it as UTF-8 CSV' % input_csv
        )
    except OSError as error:
        raise ScrapeError('cannot read %s (%s)' % (input_csv, error))

def run_sample(
    input_csv: str,
    output_csv: str,
    size: int,
    quota: Sequence[int],
    seed: Optional[int],
    exclude: Iterable[str],
    dry_run: bool
) -> int:
    """Sample the month's videos. Returns the process exit code."""
    rows, skipped = read_candidates(input_csv)

    for message in skipped:
        logger.warning(message)

    if not rows:
        logger.error('no usable rows in %s - nothing to sample' % input_csv)
        return 1

    logger.info('%d unique video(s) in %s' % (len(rows), input_csv))

    excluded_ids, exclude_sources = load_exclusions(exclude)
    if excluded_ids:
        before: int = len(rows)
        rows = [row for row in rows if row.aweme_id not in excluded_ids]
        logger.info(
            'excluded %d video(s) already scraped in earlier runs'
            % (before - len(rows))
        )

    if not rows:
        logger.error(
            'every video was excluded by --exclude - nothing left to sample. '
            'Drop --exclude, or point it at fewer runs.'
        )
        return 1

    if seed is None:
        seed = random.SystemRandom().randrange(2 ** 32)

    # An instance, not random.seed(). The global RNG is shared with the
    # scraper's request pacing, so seeding it globally would make this
    # sampler's output depend on whatever touched random first.
    rng: random.Random = random.Random(seed)

    picked, allocation, available, unfilled = sample_rows(rows, size, quota, rng)

    logger.info('seed %d' % seed)
    for tier in TIER_ORDER:
        logger.info('%-10s %4d sampled of %d available' % (
            tier, allocation[tier], available[tier]
        ))

    if unfilled:
        logger.warning(
            '%d slot(s) of the requested %d could not be filled - the mirror '
            'does not hold enough videos' % (unfilled, size)
        )

    logger.info('%d video(s) sampled, batch will take roughly %s' % (
        len(picked), estimate_duration(len(picked))
    ))

    if dry_run:
        logger.info('--dry-run: nothing written')
        return 0

    manifest: Dict[str, Any] = build_manifest(
        input_csv=input_csv,
        size=size,
        quota=quota,
        seed=seed,
        allocation=allocation,
        available=available,
        unfilled=unfilled,
        duplicates=len(skipped),
        excluded=len(excluded_ids),
        exclude_sources=exclude_sources,
        picked=len(picked)
    )

    csv_path, manifest_path = write_sample(output_csv, picked, manifest)

    logger.info('wrote %s' % csv_path)
    logger.info('wrote %s' % manifest_path)
    logger.info('next: python batch.py --input=%s' % csv_path)

    return 0
