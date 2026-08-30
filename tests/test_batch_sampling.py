"""Tests for sampling inside batch.py.

The guard is the point of these: pointing the batch at the whole order mirror
started a three-day run once, and nothing on the command line said so.
"""

import csv
import json
import os

import pytest

from click.testing import CliRunner

from tiktokcomment.runner import run_batch, MAX_UNSAMPLED_VIDEOS
from tiktokcomment.tiktokcomment import TiktokComment
from tiktokcomment.errors import ScrapeError

from batch import main as batch_main


def mirror(tmp_path, kol=0, official=0, affiliate=0, name='mirror.csv'):
    path = tmp_path / name
    lines = ['id_konten,account_type']
    video = 7000000000000000000
    for account_type, total in (
        ('kol account', kol),
        ('official account', official),
        ('affiliate account', affiliate)
    ):
        for _ in range(total):
            video += 1
            lines.append('%d,%s' % (video, account_type))
    path.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return str(path)


@pytest.fixture
def offline(monkeypatch):
    """Replace the network with one comment per video."""
    calls = []

    def fake_get(self, path, params):
        calls.append(params)
        return {
            'comments': [{
                'cid': 'c%d' % len(calls),
                'text': 'ok',
                'create_time': 1700000000,
                'user': {
                    'unique_id': 'u',
                    'nickname': 'n',
                    'avatar_thumb': {'url_list': ['a']}
                },
                'digg_count': 1,
                'reply_comment_total': 0
            }],
            'has_more': 0
        }

    monkeypatch.setattr(TiktokComment, '_TiktokComment__get', fake_get)
    return calls


class TestSizeGuard:

    def test_a_large_input_without_sample_is_refused(self, tmp_path, offline):
        source = mirror(tmp_path, affiliate=MAX_UNSAMPLED_VIDEOS + 1)

        with pytest.raises(ScrapeError) as error:
            run_batch(source, str(tmp_path), '2026-09', 200, 0, (0, 0), (0, 0), False)

        message = str(error.value)
        assert '--sample' in message and '--all' in message
        # The refusal has to name the cost, or it reads as a bug rather than a
        # warning.
        assert 'scraping' in message
        assert not offline

    def test_the_guard_names_the_video_count(self, tmp_path, offline):
        source = mirror(tmp_path, affiliate=MAX_UNSAMPLED_VIDEOS + 7)

        with pytest.raises(ScrapeError, match=str(MAX_UNSAMPLED_VIDEOS + 7)):
            run_batch(source, str(tmp_path), '2026-09', 200, 0, (0, 0), (0, 0), False)

    def test_all_overrides_the_guard(self, tmp_path, offline):
        source = mirror(tmp_path, affiliate=MAX_UNSAMPLED_VIDEOS + 3)

        code = run_batch(
            source, str(tmp_path), '2026-09', 200, 0, (0, 0), (0, 0), False,
            scrape_all=True
        )

        assert code == 0
        assert offline

    def test_a_small_input_still_needs_no_flags(self, tmp_path, offline):
        # The 100-video sample CSV must keep working exactly as before.
        source = mirror(tmp_path, affiliate=10)

        code = run_batch(source, str(tmp_path), '2026-09', 200, 0, (0, 0), (0, 0), False)

        assert code == 0

    def test_sample_lifts_the_guard(self, tmp_path, offline):
        source = mirror(tmp_path, kol=200, official=200, affiliate=200)

        code = run_batch(
            source, str(tmp_path), '2026-09', 200, 0, (0, 0), (0, 0), False,
            sample=10
        )

        assert code == 0


class TestSamplingInsideBatch:

    def test_only_the_sampled_videos_are_scraped(self, tmp_path, offline):
        source = mirror(tmp_path, kol=100, official=100, affiliate=100)

        run_batch(
            source, str(tmp_path), '2026-09', 200, 0, (0, 0), (0, 0), False,
            sample=10, quota=(50, 30, 20), seed=1
        )

        with open(str(tmp_path / '2026-09' / 'comments.json'), encoding='utf-8') as handle:
            scraped = json.load(handle)

        assert len(scraped) == 10

    def test_the_quota_is_applied(self, tmp_path, offline):
        source = mirror(tmp_path, kol=100, official=100, affiliate=100)

        run_batch(
            source, str(tmp_path), '2026-09', 200, 0, (0, 0), (0, 0), False,
            sample=100, quota=(50, 30, 20), seed=1
        )

        with open(str(tmp_path / '2026-09' / 'comments.json'), encoding='utf-8') as handle:
            scraped = json.load(handle)

        counts = {}
        for entry in scraped:
            counts[entry['account_type']] = counts.get(entry['account_type'], 0) + 1

        assert counts == {
            'kol account': 50, 'official account': 30, 'affiliate account': 20
        }

    def test_the_chosen_list_is_written_before_scraping(self, tmp_path, offline):
        source = mirror(tmp_path, kol=100, official=100, affiliate=100)

        run_batch(
            source, str(tmp_path), '2026-09', 200, 0, (0, 0), (0, 0), False,
            sample=10, seed=1
        )

        sample_csv = str(tmp_path / '2026-09' / 'sample.csv')
        manifest = str(tmp_path / '2026-09' / 'sample.manifest.json')

        assert os.path.exists(sample_csv)
        assert os.path.exists(manifest)

        with open(sample_csv, newline='', encoding='utf-8-sig') as handle:
            assert len(list(csv.DictReader(handle))) == 10

        with open(manifest, encoding='utf-8') as handle:
            assert json.load(handle)['seed'] == 1

    def test_the_same_seed_scrapes_the_same_videos(self, tmp_path, offline):
        source = mirror(tmp_path, kol=100, official=100, affiliate=100)

        def ids(month):
            run_batch(
                source, str(tmp_path), month, 200, 0, (0, 0), (0, 0), False,
                sample=10, seed=4
            )
            with open(str(tmp_path / month / 'comments.json'), encoding='utf-8') as handle:
                return sorted(entry['aweme_id'] for entry in json.load(handle))

        assert ids('2026-09') == ids('2026-10')

    def test_a_sample_larger_than_the_input_takes_everything(self, tmp_path, offline):
        source = mirror(tmp_path, kol=2, official=2, affiliate=2)

        run_batch(
            source, str(tmp_path), '2026-09', 200, 0, (0, 0), (0, 0), False,
            sample=500, seed=1
        )

        with open(str(tmp_path / '2026-09' / 'comments.json'), encoding='utf-8') as handle:
            assert len(json.load(handle)) == 6


class TestCli:

    @pytest.fixture
    def runner(self):
        return CliRunner()

    def test_a_sample_below_one_is_rejected(self, runner, tmp_path):
        source = mirror(tmp_path, affiliate=3)

        result = runner.invoke(batch_main, [
            '--input', source, '--output', str(tmp_path), '--sample', '0'
        ])

        assert result.exit_code == 1

    def test_a_quota_that_misses_100_is_rejected(self, runner, tmp_path):
        source = mirror(tmp_path, affiliate=3)

        result = runner.invoke(batch_main, [
            '--input', source, '--output', str(tmp_path),
            '--sample', '2', '--quota', '50,30,10'
        ])

        assert result.exit_code == 1

    def test_the_guard_exits_two_not_with_a_traceback(self, runner, tmp_path, offline):
        source = mirror(tmp_path, affiliate=MAX_UNSAMPLED_VIDEOS + 1)

        result = runner.invoke(batch_main, [
            '--input', source, '--output', str(tmp_path), '--month', '2026-09'
        ])

        assert result.exit_code == 2
        assert result.exception is None or isinstance(result.exception, SystemExit)
