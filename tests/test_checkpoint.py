import json

import pytest

from tiktokcomment.runner import Checkpoint, read_rows, DEFAULT_ACCOUNT_TYPE


def write_partial(tmp_path, lines):
    path = tmp_path / '.partial.jsonl'
    path.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return str(path)


def entry(aweme_id, account_type='kol', comments=None):
    return json.dumps({
        'aweme_id': aweme_id,
        'account_type': account_type,
        'comments': comments if comments is not None else []
    })


# Regression: ISSUE-002 - malformed checkpoint lines reached the final
# comments.json as records with no comments field, and a line that failed to
# parse was dropped without a word, so a truncated checkpoint lost videos
# silently on recovery.
# Found by /qa on 2026-08-28
# Report: .gstack/qa-reports/qa-report-tiktok-comment-scrapper-2026-08-28.md
def test_checkpoint_drops_entries_that_are_not_json(tmp_path):
    path = write_partial(tmp_path, [
        entry('7418294751977327878'),
        '{this is not json}'
    ])

    checkpoint = Checkpoint(path)

    assert list(checkpoint.done) == ['7418294751977327878']


def test_checkpoint_drops_entries_without_an_id(tmp_path):
    path = write_partial(tmp_path, [
        json.dumps({'caption': 'no id here', 'comments': []}),
        entry('7418294751977327878')
    ])

    checkpoint = Checkpoint(path)

    assert list(checkpoint.done) == ['7418294751977327878']
    assert None not in checkpoint.done


def test_checkpoint_drops_entries_without_a_comments_list(tmp_path):
    """A half-written line keeps its id but loses the payload."""
    path = write_partial(tmp_path, [
        json.dumps({'aweme_id': '111', 'account_type': 'kol'}),
        json.dumps({'aweme_id': '222', 'comments': 'not a list'}),
        entry('7418294751977327878')
    ])

    checkpoint = Checkpoint(path)

    assert list(checkpoint.done) == ['7418294751977327878']
    for record in checkpoint.entries():
        assert isinstance(record['comments'], list)


def test_checkpoint_warns_about_dropped_lines(tmp_path, log_messages):
    path = write_partial(tmp_path, [
        '{broken}',
        json.dumps({'aweme_id': '111'}),
        entry('7418294751977327878')
    ])

    Checkpoint(path)

    assert any('2 unreadable line(s)' in message for message in log_messages)


def test_checkpoint_stays_quiet_when_every_line_is_good(tmp_path, log_messages):
    path = write_partial(tmp_path, [entry('111'), entry('222')])

    checkpoint = Checkpoint(path)

    assert not any('unreadable' in message for message in log_messages)
    assert sorted(checkpoint.done) == ['111', '222']


def test_checkpoint_ignores_blank_lines(tmp_path):
    path = write_partial(tmp_path, [entry('111'), '', '   ', entry('222')])

    assert sorted(Checkpoint(path).done) == ['111', '222']


def test_missing_checkpoint_file_is_empty(tmp_path):
    checkpoint = Checkpoint(str(tmp_path / 'absent.jsonl'))

    assert checkpoint.done == {}
    assert checkpoint.entries() == []


def test_checkpoint_round_trips_an_added_entry(tmp_path):
    path = str(tmp_path / '.partial.jsonl')
    record = {'aweme_id': '999', 'account_type': 'affiliate', 'comments': []}

    Checkpoint(path).add(record)

    assert Checkpoint(path).has('999')


def write_csv(tmp_path, text):
    path = tmp_path / 'videos.csv'
    path.write_text(text, encoding='utf-8')
    return str(path)


def test_blank_account_type_falls_back_to_unknown(tmp_path):
    path = write_csv(tmp_path, 'url_or_id,account_type\n7418294751977327878,\n')

    rows, skipped = read_rows(path)

    assert [row.account_type for row in rows] == [DEFAULT_ACCOUNT_TYPE]
    assert skipped == []


def test_missing_account_type_column_is_allowed(tmp_path):
    path = write_csv(tmp_path, 'url_or_id\n7418294751977327878\n')

    rows, _ = read_rows(path)

    assert [row.account_type for row in rows] == [DEFAULT_ACCOUNT_TYPE]


def test_rows_without_a_video_id_are_skipped_not_fatal(tmp_path):
    path = write_csv(
        tmp_path,
        'url_or_id,account_type\n'
        '   ,kol\n'
        'not-a-video,kol\n'
        '7418294751977327878,kol\n'
    )

    rows, skipped = read_rows(path)

    assert [row.aweme_id for row in rows] == ['7418294751977327878']
    assert len(skipped) == 2


def test_duplicate_video_ids_are_skipped(tmp_path):
    path = write_csv(
        tmp_path,
        'url_or_id,account_type\n'
        '7418294751977327878,kol\n'
        'https://www.tiktok.com/@x/video/7418294751977327878,affiliate\n'
    )

    rows, skipped = read_rows(path)

    assert len(rows) == 1
    assert any('duplicate' in message for message in skipped)


def test_missing_required_column_is_fatal(tmp_path):
    from tiktokcomment.errors import ScrapeError

    path = write_csv(tmp_path, 'video,tag\n123,abc\n')

    with pytest.raises(ScrapeError, match='url_or_id'):
        read_rows(path)
