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


def test_without_llm_env_vars_it_falls_back_to_lexicon_only(tmp_path, monkeypatch):
    monkeypatch.delenv('LLM_MODEL', raising=False)
    monkeypatch.delenv('LLM_API_KEY', raising=False)

    input_path = write_input(tmp_path, [video([top_comment('c1', 'u1', 'entahlah gimana')])])
    output_path = str(tmp_path / 'analysis_result.json')

    result = CliRunner().invoke(main, ['--input', input_path, '--output', output_path])

    assert result.exit_code == 0
    with open(output_path, encoding='utf-8') as handle:
        data = json.load(handle)
    assert data['comments'][0]['sentiment_method'] == 'lexicon'


@patch('sosmed_sentiment.cli.analyze.classify_comment')
def test_with_llm_env_vars_it_uses_hybrid_classification(mock_classify, tmp_path, monkeypatch):
    monkeypatch.setenv('LLM_MODEL', 'gpt-test')
    monkeypatch.setenv('LLM_API_KEY', 'fake-key')
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


@patch('sosmed_sentiment.cli.analyze.classify_comment')
def test_over_10_percent_llm_failure_exits_3_but_still_writes_json(mock_classify, tmp_path, monkeypatch):
    monkeypatch.setenv('LLM_MODEL', 'gpt-test')
    monkeypatch.setenv('LLM_API_KEY', 'fake-key')
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
