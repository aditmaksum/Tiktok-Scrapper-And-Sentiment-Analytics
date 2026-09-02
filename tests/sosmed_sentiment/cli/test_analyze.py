import json

from unittest.mock import patch

from click.testing import CliRunner

from sosmed_sentiment.cli.analyze import main


def write_input(tmp_path, videos):
    path = tmp_path / 'comments.json'
    path.write_text(json.dumps(videos), encoding='utf-8')
    return str(path)


def video(aweme_id='1', comments=None, video_author_username=''):
    return {
        'aweme_id': aweme_id, 'caption': 'caption', 'comments': comments or [],
        'video_author_username': video_author_username
    }


def top_comment(comment_id, username, text):
    return {
        'comment_id': comment_id, 'username': username, 'comment': text,
        'create_time': '2026-08-30T00:00:00'
    }


def fake_model_classify(text_raw):
    if 'bagus' in text_raw:
        return {'sentiment_label': 'positif', 'sentiment_confidence': 0.9, 'sentiment_method': 'model'}
    if 'jelek' in text_raw:
        return {'sentiment_label': 'negatif', 'sentiment_confidence': 0.9, 'sentiment_method': 'model'}
    return {'sentiment_label': 'netral', 'sentiment_confidence': 0.9, 'sentiment_method': 'model'}


@patch('sosmed_sentiment.cli.analyze.model_classify', side_effect=fake_model_classify)
@patch('sosmed_sentiment.cli.analyze.load_model')
def test_a_valid_run_writes_analysis_result_and_exits_zero(mock_load, mock_classify, tmp_path):
    input_path = write_input(tmp_path, [
        video(comments=[
            top_comment('c1', 'user1', 'bagus banget produknya'),
            top_comment('c2', 'user2', 'jelek parah gak recommended')
        ])
    ])
    output_path = str(tmp_path / 'analysis_result.json')

    result = CliRunner().invoke(main, ['--input', input_path, '--output', output_path])

    assert result.exit_code == 0, result.output
    mock_load.assert_called_once()
    with open(output_path, encoding='utf-8') as handle:
        data = json.load(handle)

    assert data['meta']['total_comments_analyzed'] == 2
    assert data['sentiment_summary']['positif'] >= 1
    assert data['sentiment_summary']['negatif'] >= 1
    for comment in data['comments']:
        assert comment['sentiment_method'] == 'model'


def test_an_invalid_schema_exits_2_and_writes_nothing(tmp_path):
    input_path = write_input(tmp_path, [{'aweme_id': '1'}])  # missing comments
    output_path = str(tmp_path / 'analysis_result.json')

    result = CliRunner().invoke(main, ['--input', input_path, '--output', output_path])

    assert result.exit_code == 2
    import os
    assert not os.path.exists(output_path)


@patch('sosmed_sentiment.cli.analyze.model_classify', side_effect=fake_model_classify)
@patch('sosmed_sentiment.cli.analyze.load_model')
def test_video_uploader_comment_is_excluded_from_the_result(mock_load, mock_classify, tmp_path):
    input_path = write_input(tmp_path, [
        video(
            comments=[
                top_comment('c1', 'realcustomer', 'bagus banget'),
                top_comment('c2', 'dokterrizkimrd', 'terima kasih ya')
            ],
            video_author_username='dokterrizkimrd'
        )
    ])
    output_path = str(tmp_path / 'analysis_result.json')

    result = CliRunner().invoke(main, ['--input', input_path, '--output', output_path])

    assert result.exit_code == 0, result.output
    with open(output_path, encoding='utf-8') as handle:
        data = json.load(handle)

    assert data['meta']['total_comments_analyzed'] == 1
    assert data['meta']['total_comments_excluded_internal'] == 1
    assert data['comments'][0]['username'] == 'realcustomer'


def test_missing_input_file_fails_before_writing_anything(tmp_path):
    output_path = str(tmp_path / 'analysis_result.json')

    result = CliRunner().invoke(
        main, ['--input', str(tmp_path / 'does-not-exist.json'), '--output', output_path]
    )

    assert result.exit_code != 0
    import os
    assert not os.path.exists(output_path)


@patch('sosmed_sentiment.cli.analyze.load_model')
def test_a_model_load_failure_exits_2_and_writes_nothing(mock_load, tmp_path):
    from sosmed_sentiment.errors import ModelLoadError
    mock_load.side_effect = ModelLoadError('no internet')

    input_path = write_input(tmp_path, [video(comments=[top_comment('c1', 'user1', 'bagus')])])
    output_path = str(tmp_path / 'analysis_result.json')

    result = CliRunner().invoke(main, ['--input', input_path, '--output', output_path])

    assert result.exit_code == 2
    import os
    assert not os.path.exists(output_path)


@patch('sosmed_sentiment.cli.analyze.model_classify', side_effect=fake_model_classify)
@patch('sosmed_sentiment.cli.analyze.load_model')
def test_month_flag_derives_input_and_output_paths(mock_load, mock_classify, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    import os
    os.makedirs('runs/2026-08', exist_ok=True)
    with open('runs/2026-08/comments.json', 'w', encoding='utf-8') as handle:
        json.dump([video(comments=[top_comment('c1', 'user1', 'bagus banget')])], handle)

    result = CliRunner().invoke(main, ['--month', '2026-08'])

    assert result.exit_code == 0, result.output
    assert os.path.exists('runs/2026-08/analysis_result.json')


def test_no_month_and_no_input_output_is_a_usage_error(tmp_path):
    result = CliRunner().invoke(main, [])

    assert result.exit_code == 2
    assert '--month' in result.output


@patch('sosmed_sentiment.cli.analyze.model_classify', side_effect=fake_model_classify)
@patch('sosmed_sentiment.cli.analyze.load_model')
def test_a_second_run_resumes_from_the_checkpoint_without_reclassifying(
    mock_load, mock_classify, tmp_path
):
    input_path = write_input(tmp_path, [
        video(comments=[
            top_comment('c1', 'user1', 'bagus banget'),
            top_comment('c2', 'user2', 'jelek parah')
        ])
    ])
    output_path = str(tmp_path / 'analysis_result.json')

    first = CliRunner().invoke(main, ['--input', input_path, '--output', output_path])
    assert first.exit_code == 0, first.output
    assert mock_classify.call_count == 2

    mock_classify.reset_mock()
    second = CliRunner().invoke(main, ['--input', input_path, '--output', output_path])

    assert second.exit_code == 0, second.output
    mock_classify.assert_not_called()


@patch('sosmed_sentiment.cli.analyze.model_classify', side_effect=fake_model_classify)
@patch('sosmed_sentiment.cli.analyze.load_model')
def test_a_second_run_with_nothing_pending_skips_loading_the_model(
    mock_load, mock_classify, tmp_path
):
    input_path = write_input(tmp_path, [video(comments=[top_comment('c1', 'user1', 'bagus banget')])])
    output_path = str(tmp_path / 'analysis_result.json')

    CliRunner().invoke(main, ['--input', input_path, '--output', output_path])
    mock_load.reset_mock()

    result = CliRunner().invoke(main, ['--input', input_path, '--output', output_path])

    assert result.exit_code == 0, result.output
    mock_load.assert_not_called()


@patch('sosmed_sentiment.cli.analyze.model_classify', side_effect=fake_model_classify)
@patch('sosmed_sentiment.cli.analyze.load_model')
def test_fresh_flag_clears_the_checkpoint_and_reclassifies(mock_load, mock_classify, tmp_path):
    input_path = write_input(tmp_path, [
        video(comments=[top_comment('c1', 'user1', 'bagus banget')])
    ])
    output_path = str(tmp_path / 'analysis_result.json')

    CliRunner().invoke(main, ['--input', input_path, '--output', output_path])
    mock_classify.reset_mock()

    result = CliRunner().invoke(main, ['--input', input_path, '--output', output_path, '--fresh'])

    assert result.exit_code == 0, result.output
    mock_classify.assert_called_once()
