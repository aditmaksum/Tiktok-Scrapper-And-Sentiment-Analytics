"""Regression tests for the failures found in the 2026-08-28 QA pass.

Each one reproduces a way a single bad video, a stale checkpoint, or an odd
flag used to cost more than it should - the whole run, in most of them.
"""

import os

import pytest

from tiktokcomment.tiktokcomment import TiktokComment
from tiktokcomment.errors import SchemaError
from tiktokcomment.runner import Checkpoint, flatten, read_rows, run_batch

from batch import _check_month


def comment(cid='c1', text='halo', create_time=1700000000, **extra):
    raw = {
        'cid': cid,
        'text': text,
        'create_time': create_time,
        'user': {
            'unique_id': 'user',
            'nickname': 'nick',
            'avatar_thumb': {'url_list': ['http://avatar']}
        },
        'digg_count': 1,
        'reply_comment_total': 0
    }
    raw.update(extra)

    if create_time is None:
        del raw['create_time']

    return raw


def scraper(**kwargs):
    kwargs.setdefault('request_delay', (0, 0))
    return TiktokComment(**kwargs)


def pages(responses):
    """Replace the network with a fixed list of responses, then repeat the last."""
    calls = []

    def fake_get(self, path, params):
        calls.append(params)
        return responses[min(len(calls) - 1, len(responses) - 1)]

    return fake_get, calls


class TestCreateTime:
    """A comment with no usable create_time costs one video, not the run."""

    @pytest.mark.parametrize('value', [None, '', 'yesterday', {}])
    def test_an_unusable_create_time_raises_schema_error(self, value):
        # TypeError would escape run_batch, which catches only ScrapeError:
        # the batch died mid-run and the month was never assembled.
        with pytest.raises(SchemaError) as error:
            scraper()._TiktokComment__parse_comment(comment(create_time=value))

        assert 'create_time' in str(error.value)

    def test_a_numeric_string_is_still_accepted(self):
        parsed = scraper()._TiktokComment__parse_comment(
            comment(create_time='1700000000')
        )

        assert parsed.create_time.startswith('2023-11-')


class TestPagingIsBounded:
    """Blank comments do not spend the cap, so the cap cannot bound paging."""

    def test_pages_of_only_blanks_stop_at_the_page_cap(self, monkeypatch):
        fake_get, calls = pages([{
            'comments': [comment(cid=str(index), text='   ') for index in range(50)],
            'has_more': 1
        }])
        monkeypatch.setattr(TiktokComment, '_TiktokComment__get', fake_get)

        collected = scraper(max_comments=200, max_replies=0).get_all_comments('1')

        assert collected.total_collected == 0
        assert len(calls) == TiktokComment.MAX_PAGES

    def test_replies_of_only_blanks_stop_at_the_reply_page_cap(self, monkeypatch):
        fake_get, calls = pages([{
            'comments': [comment(cid='r', text='')],
            'has_more': 1
        }])
        monkeypatch.setattr(TiktokComment, '_TiktokComment__get', fake_get)

        probe = scraper(max_comments=200, max_replies=5)
        probe.aweme_id = '1'

        assert list(probe.get_replies('c1')) == []
        assert len(calls) == TiktokComment.MAX_REPLY_PAGES

    def test_a_healthy_video_still_stops_at_the_comment_cap(self, monkeypatch):
        fake_get, calls = pages([{
            'comments': [comment(cid='%d' % index) for index in range(50)],
            'has_more': 1
        }])
        monkeypatch.setattr(TiktokComment, '_TiktokComment__get', fake_get)

        collected = scraper(max_comments=200, max_replies=0).get_all_comments('1')

        assert collected.total_collected == 200
        assert len(calls) == 4


class TestFlatten:
    """A checkpoint entry with missing fields still writes a CSV line."""

    def test_a_comment_without_every_field_does_not_raise(self):
        lines = list(flatten({'aweme_id': '1', 'comments': [{'comment_id': 'x'}]}))

        assert lines[0]['comment_id'] == 'x'
        assert lines[0]['username'] == ''
        assert lines[0]['digg_count'] == 0

    def test_a_reply_is_still_joined_to_its_parent(self):
        lines = list(flatten({
            'aweme_id': '1',
            'comments': [{'comment_id': 'p', 'replies': [{'comment_id': 'r'}]}]
        }))

        assert lines[1]['parent_comment_id'] == 'p'
        assert lines[1]['is_reply'] == 1


class TestCheckpointPath:

    def test_a_bare_filename_needs_no_directory(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)

        checkpoint = Checkpoint('partial.jsonl')
        checkpoint.add({'aweme_id': '1', 'comments': []})

        assert Checkpoint('partial.jsonl').has('1')


class TestMonthLabel:

    @pytest.mark.parametrize('value', ['C:', 'D:', 'C:runs', '2026-08:1'])
    def test_a_drive_label_is_rejected(self, value):
        # os.path.join(output, 'C:') is just 'C:' - the whole --output is lost.
        with pytest.raises(ValueError) as error:
            _check_month(value)

        assert 'drive' in str(error.value)

    def test_a_plain_month_is_still_accepted(self):
        assert _check_month('2026-08') == '2026-08'


class TestResumeWithNothingLeft:
    """A rerun of a finished month must not touch the network at all."""

    def _csv(self, tmp_path):
        path = tmp_path / 'videos.csv'
        path.write_text(
            'url_or_id,account_type\n7418294751977327878,aff\n', encoding='utf-8'
        )
        return str(path)

    def test_a_finished_month_makes_no_requests(self, tmp_path, monkeypatch):
        from tiktokcomment import runner

        fake_get, calls = pages([{
            'comments': [comment()],
            'has_more': 0
        }])
        monkeypatch.setattr(TiktokComment, '_TiktokComment__get', fake_get)

        arguments = dict(
            input_csv=self._csv(tmp_path),
            output_dir=str(tmp_path),
            month='2026-08',
            max_comments=200,
            max_replies=0,
            video_delay=(0, 0),
            request_delay=(0, 0),
            fresh=False
        )

        assert runner.run_batch(**arguments) == 0
        first_run = len(calls)
        assert first_run

        # The smoke test used to probe videos already in the checkpoint, so a
        # rerun spent requests - and failed outright if those videos had their
        # comments turned off.
        assert runner.run_batch(**arguments) == 0
        assert len(calls) == first_run

    def test_the_month_is_still_written_on_that_rerun(self, tmp_path, monkeypatch):
        from tiktokcomment import runner

        fake_get, _ = pages([{'comments': [comment()], 'has_more': 0}])
        monkeypatch.setattr(TiktokComment, '_TiktokComment__get', fake_get)

        arguments = dict(
            input_csv=self._csv(tmp_path),
            output_dir=str(tmp_path),
            month='2026-08',
            max_comments=200,
            max_replies=0,
            video_delay=(0, 0),
            request_delay=(0, 0),
            fresh=False
        )

        runner.run_batch(**arguments)
        os.remove(str(tmp_path / '2026-08' / 'comments.csv'))
        runner.run_batch(**arguments)

        assert os.path.exists(str(tmp_path / '2026-08' / 'comments.csv'))


class TestCreatorColumn:
    """FR-11: the creator's own username, read from the CSV, not scraped."""

    def _csv(self, tmp_path, header, row):
        path = tmp_path / 'videos.csv'
        path.write_text('%s\n%s\n' % (header, row), encoding='utf-8')
        return str(path)

    def test_nama_pengguna_kreator_is_read(self, tmp_path):
        path = self._csv(
            tmp_path,
            'id_konten,nama_pengguna_kreator,account_type',
            '7418294751977327878,dokterrizkimrd,kol'
        )

        rows, skipped = read_rows(path, resolve_short_links=False)

        assert not skipped
        assert rows[0].creator_username == 'dokterrizkimrd'

    def test_creator_username_alt_name_is_also_read(self, tmp_path):
        path = self._csv(
            tmp_path,
            'url_or_id,creator_username',
            '7418294751977327878,dokterrizkimrd'
        )

        rows, _ = read_rows(path, resolve_short_links=False)

        assert rows[0].creator_username == 'dokterrizkimrd'

    def test_an_older_csv_without_the_column_defaults_to_empty(self, tmp_path):
        path = self._csv(tmp_path, 'url_or_id,account_type', '7418294751977327878,kol')

        rows, _ = read_rows(path, resolve_short_links=False)

        assert rows[0].creator_username == ''

    def test_flatten_carries_the_video_author_username(self):
        lines = list(flatten({
            'aweme_id': '1',
            'video_author_username': 'dokterrizkimrd',
            'comments': [{'comment_id': 'c1'}]
        }))

        assert lines[0]['video_author_username'] == 'dokterrizkimrd'


class TestCreatorUsernameTypoWarning:
    """Issue 6: a hand-typed column that matches nothing warns, never errors."""

    def _csv(self, tmp_path, creator_username):
        path = tmp_path / 'videos.csv'
        path.write_text(
            'url_or_id,nama_pengguna_kreator\n7418294751977327878,%s\n'
            % creator_username,
            encoding='utf-8'
        )
        return str(path)

    def _run(self, tmp_path, monkeypatch, creator_username, commenter):
        fake_get, _ = pages([{
            'comments': [comment(cid='c1', **{'user': {
                'unique_id': commenter, 'nickname': commenter,
                'avatar_thumb': {'url_list': ['http://avatar']}
            }})],
            'has_more': 0
        }])
        monkeypatch.setattr(TiktokComment, '_TiktokComment__get', fake_get)

        return run_batch(
            input_csv=self._csv(tmp_path, creator_username),
            output_dir=str(tmp_path),
            month='2026-08',
            max_comments=200,
            max_replies=0,
            video_delay=(0, 0),
            request_delay=(0, 0),
            fresh=False
        )

    def test_a_typo_warns(self, tmp_path, monkeypatch, log_messages):
        self._run(tmp_path, monkeypatch, 'dokterrizkimrd', commenter='someoneelse')

        assert any(
            'never appears' in message and 'dokterrizkimrd' in message
            for message in log_messages
        )

    def test_a_match_does_not_warn(self, tmp_path, monkeypatch, log_messages):
        self._run(tmp_path, monkeypatch, 'dokterrizkimrd', commenter='dokterrizkimrd')

        assert not any('never appears' in message for message in log_messages)

    def test_an_empty_creator_column_does_not_warn(self, tmp_path, monkeypatch, log_messages):
        self._run(tmp_path, monkeypatch, '', commenter='someoneelse')

        assert not any('never appears' in message for message in log_messages)
