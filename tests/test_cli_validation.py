import pytest

from click.testing import CliRunner

import batch
import main as single


def logged(messages, fragment):
    return any(fragment in message for message in messages)


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def videos_csv(tmp_path):
    path = tmp_path / 'videos.csv'
    path.write_text(
        'url_or_id,account_type\n7418294751977327878,kol\n',
        encoding='utf-8'
    )
    return str(path)


# Regression: ISSUE-001 - a cap of zero scraped nothing, exited 0 as if it had
# succeeded, and still wrote every video into the checkpoint, so a rerun with a
# correct cap skipped them all and the month stayed empty.
# Found by /qa on 2026-08-28
# Report: .gstack/qa-reports/qa-report-tiktok-comment-scrapper-2026-08-28.md
@pytest.mark.parametrize('cap', [0, -1, -200])
def test_batch_rejects_non_positive_max_comments(runner, videos_csv, tmp_path, log_messages, cap):
    result = runner.invoke(batch.main, [
        '--input', videos_csv,
        '--output', str(tmp_path / 'out'),
        '--max-comments', str(cap)
    ])

    assert result.exit_code == 1
    assert logged(log_messages, '--max-comments must be at least 1')
    # Nothing may be written, or the checkpoint would claim the videos are done.
    assert not (tmp_path / 'out').exists()


@pytest.mark.parametrize('cap', [-1, -10])
def test_batch_rejects_negative_max_replies(runner, videos_csv, tmp_path, log_messages, cap):
    result = runner.invoke(batch.main, [
        '--input', videos_csv,
        '--output', str(tmp_path / 'out'),
        '--max-replies', str(cap)
    ])

    assert result.exit_code == 1
    assert logged(log_messages, '--max-replies cannot be negative')
    assert not (tmp_path / 'out').exists()


@pytest.mark.parametrize('size', [0, -5])
def test_single_video_cli_rejects_non_positive_size(runner, tmp_path, log_messages, size):
    result = runner.invoke(single.main, [
        '--aweme_id', '7418294751977327878',
        '--size', str(size),
        '--output', str(tmp_path / 'data')
    ])

    assert result.exit_code == 1
    assert logged(log_messages, '--size must be at least 1')
    assert not (tmp_path / 'data').exists()


def test_max_comments_of_one_is_allowed(runner, videos_csv, tmp_path, log_messages):
    """The boundary the cap check must not reject."""
    runner.invoke(batch.main, [
        '--input', videos_csv,
        '--output', str(tmp_path / 'out'),
        '--max-comments', '1',
        '--video-delay', 'nonsense'
    ])

    # It fails on the delay flag, which is parsed after the caps: proof that a
    # cap of 1 got through the check rather than being rejected with the zeros.
    assert not logged(log_messages, '--max-comments')
    assert logged(log_messages, 'MIN,MAX')


# Regression: ISSUE-003 - a non-numeric delay leaked Python's own
# "could not convert string to float" instead of naming the expected format.
# Found by /qa on 2026-08-28
# Report: .gstack/qa-reports/qa-report-tiktok-comment-scrapper-2026-08-28.md
@pytest.mark.parametrize('value', ['a,b', 'x,1', '1,y'])
def test_parse_range_reports_the_expected_format(value):
    with pytest.raises(ValueError) as raised:
        batch._parse_range(value)

    message = str(raised.value)
    assert 'MIN,MAX' in message
    assert 'could not convert' not in message


@pytest.mark.parametrize('value', ['5', '1,2,3', ''])
def test_parse_range_rejects_wrong_field_count(value):
    with pytest.raises(ValueError, match='MIN,MAX'):
        batch._parse_range(value)


@pytest.mark.parametrize('value', ['10,2', '-1,5'])
def test_parse_range_rejects_bad_bounds(value):
    with pytest.raises(ValueError, match='0 <= MIN <= MAX'):
        batch._parse_range(value)


def test_parse_range_accepts_valid_input():
    assert batch._parse_range('7,10') == (7.0, 10.0)
    assert batch._parse_range('0,0') == (0.0, 0.0)


# Regression: ISSUE-004 - --month went straight into os.path.join, so
# "../../elsewhere" wrote the month's output outside the --output directory.
# Found by /qa on 2026-08-28
# Report: .gstack/qa-reports/qa-report-tiktok-comment-scrapper-2026-08-28.md
@pytest.mark.parametrize('value', [
    '../../elsewhere',
    '..',
    'a/b',
    '2026-08/../..'
])
def test_check_month_rejects_paths(value):
    with pytest.raises(ValueError, match='folder name, not a path'):
        batch._check_month(value)


def test_check_month_accepts_a_plain_label():
    assert batch._check_month('2026-08') == '2026-08'
