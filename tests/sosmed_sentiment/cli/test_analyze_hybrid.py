import json

from unittest.mock import patch

from click.testing import CliRunner

from sosmed_sentiment.cli.analyze import main


def write_input(tmp_path, videos):
    path = tmp_path / 'comments.json'
    path.write_text(json.dumps(videos), encoding='utf-8')
    return str(path)


def video(comments):
    return {'aweme_id': '1', 'caption': 'caption', 'comments': comments, 'video_author_username': ''}


def top_comment(comment_id, username, text):
    return {
        'comment_id': comment_id, 'username': username, 'comment': text,
        'create_time': '2026-08-30T00:00:00'
    }


@patch('sosmed_sentiment.cli.analyze.model_classify')
@patch('sosmed_sentiment.cli.analyze.load_model')
def test_without_llm_env_vars_it_runs_model_only(mock_load, mock_model, tmp_path, monkeypatch):
    monkeypatch.delenv('LLM_MODEL', raising=False)
    monkeypatch.delenv('LLM_API_KEY', raising=False)
    mock_model.return_value = {
        'sentiment_label': 'netral', 'sentiment_confidence': 0.5, 'sentiment_method': 'model'
    }

    input_path = write_input(tmp_path, [video([top_comment('c1', 'u1', 'entahlah gimana')])])
    output_path = str(tmp_path / 'analysis_result.json')

    result = CliRunner().invoke(main, ['--input', input_path, '--output', output_path])

    assert result.exit_code == 0, result.output
    with open(output_path, encoding='utf-8') as handle:
        data = json.load(handle)
    assert data['comments'][0]['sentiment_method'] == 'model'


@patch('sosmed_sentiment.cli.analyze.load_threshold_config')
@patch('sosmed_sentiment.cli.analyze.classify_comment')
@patch('sosmed_sentiment.cli.analyze.load_model')
def test_with_llm_env_vars_it_uses_hybrid_classification(
    mock_load, mock_classify, mock_threshold, tmp_path, monkeypatch
):
    monkeypatch.setenv('LLM_MODEL', 'gpt-test')
    monkeypatch.setenv('LLM_API_KEY', 'fake-key')
    mock_threshold.return_value = 0.6
    mock_classify.return_value = {
        'sentiment_label': 'positif', 'sentiment_confidence': 0.9, 'sentiment_method': 'llm'
    }

    input_path = write_input(tmp_path, [video([top_comment('c1', 'u1', 'entahlah gimana')])])
    output_path = str(tmp_path / 'analysis_result.json')

    result = CliRunner().invoke(main, ['--input', input_path, '--output', output_path])

    assert result.exit_code == 0, result.output
    mock_classify.assert_called_once()
    with open(output_path, encoding='utf-8') as handle:
        data = json.load(handle)
    assert data['comments'][0]['sentiment_method'] == 'llm'


@patch('sosmed_sentiment.cli.analyze.load_threshold_config')
@patch('sosmed_sentiment.cli.analyze.classify_comment')
@patch('sosmed_sentiment.cli.analyze.load_model')
def test_over_10_percent_llm_failure_exits_3_but_still_writes_json(
    mock_load, mock_classify, mock_threshold, tmp_path, monkeypatch
):
    monkeypatch.setenv('LLM_MODEL', 'gpt-test')
    monkeypatch.setenv('LLM_API_KEY', 'fake-key')
    mock_threshold.return_value = 0.6
    mock_classify.return_value = {
        'sentiment_label': 'tidak_terklasifikasi', 'sentiment_confidence': 0.0,
        'sentiment_method': 'llm_failed'
    }

    input_path = write_input(tmp_path, [video([top_comment('c1', 'u1', 'entahlah gimana')])])
    output_path = str(tmp_path / 'analysis_result.json')

    result = CliRunner().invoke(main, ['--input', input_path, '--output', output_path])

    assert result.exit_code == 3
    import os
    assert os.path.exists(output_path)


@patch('sosmed_sentiment.cli.analyze.load_model')
def test_hybrid_enabled_without_threshold_config_exits_2_not_a_raw_traceback(
    mock_load, tmp_path, monkeypatch
):
    monkeypatch.setenv('LLM_MODEL', 'gpt-test')
    monkeypatch.setenv('LLM_API_KEY', 'fake-key')

    input_path = write_input(tmp_path, [video([top_comment('c1', 'u1', 'entahlah gimana')])])
    output_path = str(tmp_path / 'analysis_result.json')

    result = CliRunner().invoke(main, ['--input', input_path, '--output', output_path])

    assert result.exit_code == 2, result.output
    assert result.exception is None or isinstance(result.exception, SystemExit)


@patch('sosmed_sentiment.cli.analyze.load_threshold_config')
@patch('sosmed_sentiment.cli.analyze.classify_comment')
@patch('sosmed_sentiment.cli.analyze.model_classify')
@patch('sosmed_sentiment.cli.analyze.load_model')
def test_a_comment_checkpointed_model_only_is_reclassified_once_llm_is_configured(
    mock_load, mock_model, mock_classify, mock_threshold, tmp_path, monkeypatch
):
    """A comment cached with hybrid_enabled=False must not be silently reused
    once LLM escalation is turned on - it was never evaluated against the
    threshold, so reusing it would mix classification modes in one output
    with no signal that it happened.
    """
    input_path = write_input(tmp_path, [video([top_comment('c1', 'u1', 'entahlah gimana')])])
    output_path = str(tmp_path / 'analysis_result.json')

    monkeypatch.delenv('LLM_MODEL', raising=False)
    monkeypatch.delenv('LLM_API_KEY', raising=False)
    mock_model.return_value = {
        'sentiment_label': 'netral', 'sentiment_confidence': 0.5, 'sentiment_method': 'model'
    }
    first = CliRunner().invoke(main, ['--input', input_path, '--output', output_path])
    assert first.exit_code == 0, first.output
    mock_model.assert_called_once()

    monkeypatch.setenv('LLM_MODEL', 'gpt-test')
    monkeypatch.setenv('LLM_API_KEY', 'fake-key')
    mock_threshold.return_value = 0.6
    mock_classify.return_value = {
        'sentiment_label': 'positif', 'sentiment_confidence': 0.9, 'sentiment_method': 'llm'
    }
    second = CliRunner().invoke(main, ['--input', input_path, '--output', output_path])

    assert second.exit_code == 0, second.output
    mock_classify.assert_called_once()
    with open(output_path, encoding='utf-8') as handle:
        data = json.load(handle)
    assert data['comments'][0]['sentiment_method'] == 'llm'
