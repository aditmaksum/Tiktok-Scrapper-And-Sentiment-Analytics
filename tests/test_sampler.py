"""Tests for the monthly video sampler.

The quota rules are the part worth guarding: affiliate must never come back
empty while affiliate videos exist, and the same seed must always produce the
same sample. Everything else is detail around those two.
"""

import csv
import json
import os
import random

import pytest

from tiktokcomment.runner import Row, safe_cell
from tiktokcomment.errors import ScrapeError
from tiktokcomment import sampler

from sample import main as sample_main


def rows(**counts):
    """Build candidate rows: rows(kol=3, affiliate=5)."""
    built = []
    line = 2
    for account_type, total in counts.items():
        for index in range(total):
            built.append(Row(line, '%s-%d' % (account_type, index), account_type))
            line += 1
    return built


def tier_counts(picked):
    counts = {tier: 0 for tier in sampler.TIER_ORDER}
    for row in picked:
        counts[sampler.classify_tier(row.account_type)] += 1
    return counts


class TestClassifyTier:

    @pytest.mark.parametrize('value,expected', [
        ('kol account', 'kol'),
        ('KOL ACCOUNT', 'kol'),
        ('official store', 'official'),
        ('Official', 'official'),
        ('affiliate account', 'affiliate'),
        ('AFFILIATE', 'affiliate'),
        ('reseller', 'unknown'),
        ('', 'unknown'),
        ('unknown', 'unknown'),
    ])
    def test_free_text_lands_in_the_right_tier(self, value, expected):
        assert sampler.classify_tier(value) == expected

    def test_none_is_unknown(self):
        assert sampler.classify_tier(None) == 'unknown'

    def test_the_higher_tier_wins_when_two_keywords_match(self):
        # 'kol official' is a KOL video: the higher tier is the one worth
        # guaranteeing a slot.
        assert sampler.classify_tier('kol official') == 'kol'


class TestParseQuota:

    def test_the_default_is_accepted(self):
        assert sampler.parse_quota('50,30,20') == (50, 30, 20)

    @pytest.mark.parametrize('value', ['50,30', '50,30,20,10', '50'])
    def test_wrong_field_count_is_rejected(self, value):
        with pytest.raises(ValueError, match='three'):
            sampler.parse_quota(value)

    def test_non_numbers_are_rejected_with_the_format(self):
        with pytest.raises(ValueError, match='whole numbers'):
            sampler.parse_quota('half,30,20')

    def test_a_negative_percentage_is_rejected(self):
        with pytest.raises(ValueError, match='negative'):
            sampler.parse_quota('-10,60,50')

    @pytest.mark.parametrize('value', ['50,30,10', '60,30,20'])
    def test_it_must_add_up_to_100(self, value):
        with pytest.raises(ValueError, match='add up to 100'):
            sampler.parse_quota(value)


class TestAllocateQuota:

    def test_an_exact_split(self):
        available = {'kol': 500, 'official': 500, 'affiliate': 500, 'unknown': 0}
        allocation, unfilled = sampler.allocate_quota(150, (50, 30, 20), available)

        assert allocation == {'kol': 75, 'official': 45, 'affiliate': 30, 'unknown': 0}
        assert unfilled == 0

    def test_a_split_with_a_remainder_still_totals_the_size(self):
        # 151 at 50/30/20 is 75.5 / 45.3 / 30.2 - the leftover slot goes to the
        # largest fraction, which is KOL.
        available = {'kol': 500, 'official': 500, 'affiliate': 500, 'unknown': 0}
        allocation, unfilled = sampler.allocate_quota(151, (50, 30, 20), available)

        assert sum(allocation.values()) == 151
        assert allocation['kol'] == 76
        assert unfilled == 0

    @pytest.mark.parametrize('size', range(1, 60))
    def test_the_total_always_equals_the_size(self, size):
        available = {tier: 1000 for tier in sampler.TIER_ORDER}
        allocation, unfilled = sampler.allocate_quota(size, (50, 30, 20), available)

        assert sum(allocation.values()) == size
        assert unfilled == 0

    def test_spillover_flows_down_one_tier(self):
        # 20 KOL videos exist but 75 slots were allocated. The 55 spare slots
        # go to official, not to waste.
        available = {'kol': 20, 'official': 500, 'affiliate': 500, 'unknown': 0}
        allocation, unfilled = sampler.allocate_quota(150, (50, 30, 20), available)

        assert allocation['kol'] == 20
        assert allocation['official'] == 45 + 55
        assert allocation['affiliate'] == 30
        assert unfilled == 0

    def test_spillover_chains_two_tiers_down(self):
        available = {'kol': 0, 'official': 10, 'affiliate': 500, 'unknown': 0}
        allocation, unfilled = sampler.allocate_quota(150, (50, 30, 20), available)

        assert allocation == {
            'kol': 0, 'official': 10, 'affiliate': 140, 'unknown': 0
        }
        assert unfilled == 0

    def test_unknown_only_ever_receives_spillover(self):
        # unknown has no share of 50/30/20; it exists so those rows are not
        # silently thrown away.
        available = {'kol': 0, 'official': 0, 'affiliate': 0, 'unknown': 500}
        allocation, _ = sampler.allocate_quota(150, (50, 30, 20), available)

        assert allocation['unknown'] == 150

    def test_a_mirror_too_small_reports_the_unfilled_slots(self):
        available = {'kol': 5, 'official': 5, 'affiliate': 5, 'unknown': 0}
        allocation, unfilled = sampler.allocate_quota(150, (50, 30, 20), available)

        assert sum(allocation.values()) == 15
        assert unfilled == 135


class TestSampleRows:

    def test_affiliate_is_never_empty_while_affiliate_videos_exist(self):
        # The whole point of the quota. Priority fill alone would hand every
        # slot to KOL and official here and leave affiliate at zero.
        candidates = rows(kol=500, official=500, affiliate=500)
        picked, _, _, _ = sampler.sample_rows(
            candidates, 150, (50, 30, 20), random.Random(1)
        )

        assert tier_counts(picked)['affiliate'] == 30

    def test_the_split_follows_the_quota(self):
        candidates = rows(kol=200, official=200, affiliate=200)
        picked, _, _, _ = sampler.sample_rows(
            candidates, 100, (50, 30, 20), random.Random(1)
        )

        counts = tier_counts(picked)
        assert (counts['kol'], counts['official'], counts['affiliate']) == (50, 30, 20)

    def test_a_custom_quota_is_honoured(self):
        candidates = rows(kol=200, official=200, affiliate=200)
        picked, _, _, _ = sampler.sample_rows(
            candidates, 100, (10, 10, 80), random.Random(1)
        )

        counts = tier_counts(picked)
        assert (counts['kol'], counts['official'], counts['affiliate']) == (10, 10, 80)

    def test_the_same_seed_gives_the_same_sample(self):
        candidates = rows(kol=100, official=100, affiliate=100)

        first, _, _, _ = sampler.sample_rows(
            candidates, 50, (50, 30, 20), random.Random(7)
        )
        second, _, _, _ = sampler.sample_rows(
            candidates, 50, (50, 30, 20), random.Random(7)
        )

        assert [row.aweme_id for row in first] == [row.aweme_id for row in second]

    def test_a_different_seed_gives_a_different_sample(self):
        candidates = rows(kol=100, official=100, affiliate=100)

        first, _, _, _ = sampler.sample_rows(
            candidates, 50, (50, 30, 20), random.Random(7)
        )
        second, _, _, _ = sampler.sample_rows(
            candidates, 50, (50, 30, 20), random.Random(8)
        )

        assert [row.aweme_id for row in first] != [row.aweme_id for row in second]

    def test_the_global_rng_does_not_change_the_result(self):
        # The scraper's request pacing uses the global random module. Seeding it
        # must not move the sampler's output.
        candidates = rows(kol=100, official=100, affiliate=100)

        random.seed(0)
        first, _, _, _ = sampler.sample_rows(
            candidates, 50, (50, 30, 20), random.Random(7)
        )
        random.seed(999)
        second, _, _, _ = sampler.sample_rows(
            candidates, 50, (50, 30, 20), random.Random(7)
        )

        assert [row.aweme_id for row in first] == [row.aweme_id for row in second]

    def test_the_output_is_not_grouped_by_tier(self):
        # Grouped output means a batch that dies partway collected only KOL.
        candidates = rows(kol=100, official=100, affiliate=100)
        picked, _, _, _ = sampler.sample_rows(
            candidates, 60, (50, 30, 20), random.Random(3)
        )

        sequence = [sampler.classify_tier(row.account_type) for row in picked]
        grouped = sorted(sequence, key=sampler.TIER_ORDER.index)

        assert sequence != grouped

    def test_asking_for_more_than_exists_returns_everything(self):
        candidates = rows(kol=2, official=2, affiliate=2)
        picked, _, _, unfilled = sampler.sample_rows(
            candidates, 150, (50, 30, 20), random.Random(1)
        )

        assert len(picked) == 6
        assert unfilled == 144


class TestExclusions:

    def _write_run(self, tmp_path, name, ids):
        path = tmp_path / name
        path.write_text(
            json.dumps([{'aweme_id': value, 'comments': []} for value in ids]),
            encoding='utf-8'
        )
        return str(path)

    def test_ids_from_an_earlier_run_are_returned(self, tmp_path):
        self._write_run(tmp_path, 'comments.json', ['1', '2'])

        excluded, sources = sampler.load_exclusions([str(tmp_path / '*.json')])

        assert excluded == {'1', '2'}
        assert sources

    def test_a_malformed_file_is_ignored_not_fatal(self, tmp_path):
        (tmp_path / 'broken.json').write_text('{not json', encoding='utf-8')

        excluded, _ = sampler.load_exclusions([str(tmp_path / '*.json')])

        assert excluded == set()

    def test_a_pattern_matching_nothing_is_ignored(self, tmp_path):
        excluded, _ = sampler.load_exclusions([str(tmp_path / 'nope-*.json')])

        assert excluded == set()


class TestSafeCell:

    @pytest.mark.parametrize('value', ['=cmd', '+1', '-1', '@SUM(A1)'])
    def test_a_formula_is_neutralised(self, value):
        assert safe_cell(value) == "'" + value

    def test_ordinary_text_is_untouched(self):
        assert safe_cell('bagus banget') == 'bagus banget'

    def test_non_strings_pass_through(self):
        assert safe_cell(12) == 12


class TestEstimateDuration:

    def test_minutes_for_a_small_sample(self):
        assert sampler.estimate_duration(10) == '20m'

    def test_hours_for_a_full_month(self):
        # 150 videos at 123 seconds each is a little over five hours.
        assert sampler.estimate_duration(150) == '5h 7m'


class TestOffline:

    def test_the_sampler_never_opens_a_socket(self, tmp_path, monkeypatch):
        from requests import Session

        def explode(*args, **kwargs):
            raise AssertionError('the sampler made a network call')

        monkeypatch.setattr(Session, 'head', explode)
        monkeypatch.setattr(Session, 'get', explode)

        source = tmp_path / 'mirror.csv'
        source.write_text(
            'id_konten,account_type\n'
            'https://vt.tiktok.com/ZSabc123/,kol account\n'
            '7418294751977327878,affiliate account\n',
            encoding='utf-8'
        )

        candidates, _ = sampler.read_candidates(str(source))

        assert len(candidates) == 2

    def test_a_short_link_keeps_its_raw_value_as_identity(self, tmp_path):
        source = tmp_path / 'mirror.csv'
        source.write_text(
            'id_konten,account_type\nhttps://vt.tiktok.com/ZSabc123/,kol account\n',
            encoding='utf-8'
        )

        candidates, _ = sampler.read_candidates(str(source))

        assert candidates[0].aweme_id == 'https://vt.tiktok.com/ZSabc123/'


class TestRunSample:

    def _mirror(self, tmp_path, kol=40, official=40, affiliate=400):
        path = tmp_path / 'mirror.csv'
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

    def test_it_writes_a_csv_batch_can_read(self, tmp_path):
        output = str(tmp_path / 'sample.csv')

        code = sampler.run_sample(
            input_csv=self._mirror(tmp_path),
            output_csv=output,
            size=100,
            quota=(50, 30, 20),
            seed=5,
            exclude=(),
            dry_run=False
        )

        assert code == 0

        with open(output, newline='', encoding='utf-8-sig') as handle:
            written = list(csv.DictReader(handle))

        assert len(written) == 100
        assert set(written[0]) == {'url_or_id', 'account_type'}

        # The output has to survive the reader on the other side.
        from tiktokcomment.runner import read_rows
        back, skipped = read_rows(output)
        assert len(back) == 100
        assert not skipped

    def test_the_manifest_records_the_seed_and_the_split(self, tmp_path):
        output = str(tmp_path / 'sample.csv')

        sampler.run_sample(
            input_csv=self._mirror(tmp_path),
            output_csv=output,
            size=100,
            quota=(50, 30, 20),
            seed=5,
            exclude=(),
            dry_run=False
        )

        with open(str(tmp_path / 'sample.manifest.json'), encoding='utf-8') as handle:
            manifest = json.load(handle)

        assert manifest['seed'] == 5
        assert manifest['sampled_per_tier'] == {
            'kol': 40, 'official': 40, 'affiliate': 20, 'unknown': 0
        }
        assert manifest['estimated_batch_duration']

    def test_the_recorded_seed_reproduces_the_sample(self, tmp_path):
        source = self._mirror(tmp_path)
        first = str(tmp_path / 'first.csv')
        second = str(tmp_path / 'second.csv')

        sampler.run_sample(source, first, 100, (50, 30, 20), None, (), False)

        with open(str(tmp_path / 'first.manifest.json'), encoding='utf-8') as handle:
            seed = json.load(handle)['seed']

        sampler.run_sample(source, second, 100, (50, 30, 20), seed, (), False)

        assert open(first, encoding='utf-8-sig').read() \
            == open(second, encoding='utf-8-sig').read()

    def test_dry_run_writes_nothing(self, tmp_path):
        output = str(tmp_path / 'sample.csv')

        code = sampler.run_sample(
            input_csv=self._mirror(tmp_path),
            output_csv=output,
            size=100,
            quota=(50, 30, 20),
            seed=5,
            exclude=(),
            dry_run=True
        )

        assert code == 0
        assert not os.path.exists(output)

    def test_a_mirror_of_one_repeated_video_yields_one_row(self, tmp_path):
        # What a hostile QA engineer writes: 5000 order rows, one video.
        path = tmp_path / 'mirror.csv'
        path.write_text(
            'id_konten,account_type\n'
            + '7418294751977327878,affiliate account\n' * 5000,
            encoding='utf-8'
        )
        output = str(tmp_path / 'sample.csv')

        sampler.run_sample(str(path), output, 150, (50, 30, 20), 1, (), False)

        with open(output, newline='', encoding='utf-8-sig') as handle:
            assert len(list(csv.DictReader(handle))) == 1

    def test_an_empty_mirror_exits_one(self, tmp_path):
        path = tmp_path / 'mirror.csv'
        path.write_text('id_konten,account_type\n', encoding='utf-8')

        code = sampler.run_sample(
            str(path), str(tmp_path / 'out.csv'), 10, (50, 30, 20), 1, (), False
        )

        assert code == 1

    def test_excluding_everything_exits_one(self, tmp_path):
        source = self._mirror(tmp_path, kol=1, official=0, affiliate=0)

        from tiktokcomment.runner import read_rows
        candidates, _ = read_rows(source)
        (tmp_path / 'done.json').write_text(
            json.dumps([
                {'aweme_id': row.aweme_id, 'comments': []} for row in candidates
            ]),
            encoding='utf-8'
        )

        code = sampler.run_sample(
            source, str(tmp_path / 'out.csv'), 10, (50, 30, 20), 1,
            (str(tmp_path / 'done.json'),), False
        )

        assert code == 1

    def test_a_formula_in_account_type_is_neutralised(self, tmp_path):
        path = tmp_path / 'mirror.csv'
        path.write_text(
            'id_konten,account_type\n7418294751977327878,"=cmd|calc"\n',
            encoding='utf-8'
        )
        output = str(tmp_path / 'sample.csv')

        sampler.run_sample(str(path), output, 10, (50, 30, 20), 1, (), False)

        assert "'=cmd|calc" in open(output, encoding='utf-8-sig').read()


class TestWriteErrors:

    def test_a_directory_as_output_is_a_scrape_error(self, tmp_path):
        with pytest.raises(ScrapeError, match='not a directory'):
            sampler.write_sample(str(tmp_path), [], {})

    def test_a_missing_input_is_a_scrape_error(self, tmp_path):
        with pytest.raises(ScrapeError, match='cannot read'):
            sampler.read_candidates(str(tmp_path / 'nope.csv'))

    def test_a_non_utf8_input_names_the_encoding(self, tmp_path):
        path = tmp_path / 'mirror.csv'
        path.write_bytes(b'id_konten,account_type\n\xff\xfe123456,kol\n')

        with pytest.raises(ScrapeError, match='UTF-8'):
            sampler.read_candidates(str(path))


class TestCli:

    @pytest.fixture
    def runner(self):
        from click.testing import CliRunner
        return CliRunner()

    @pytest.fixture
    def mirror(self, tmp_path):
        path = tmp_path / 'mirror.csv'
        path.write_text(
            'id_konten,account_type\n7418294751977327878,kol account\n',
            encoding='utf-8'
        )
        return str(path)

    @pytest.mark.parametrize('size', ['0', '-5'])
    def test_a_size_below_one_is_rejected(self, runner, mirror, tmp_path, size):
        result = runner.invoke(sample_main, [
            '--input', mirror, '--size', size,
            '--output', str(tmp_path / 'out.csv')
        ])

        assert result.exit_code == 1

    def test_a_quota_that_misses_100_is_rejected(self, runner, mirror, tmp_path):
        result = runner.invoke(sample_main, [
            '--input', mirror, '--quota', '50,30,10',
            '--output', str(tmp_path / 'out.csv')
        ])

        assert result.exit_code == 1

    def test_a_missing_input_file_is_rejected_by_click(self, runner, tmp_path):
        result = runner.invoke(sample_main, ['--input', str(tmp_path / 'nope.csv')])

        assert result.exit_code == 2

    def test_a_dry_run_succeeds_without_writing(self, runner, mirror, tmp_path):
        output = str(tmp_path / 'out.csv')
        result = runner.invoke(sample_main, [
            '--input', mirror, '--size', '1', '--output', output, '--dry-run'
        ])

        assert result.exit_code == 0
        assert not os.path.exists(output)
