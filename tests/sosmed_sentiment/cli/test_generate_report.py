import json
import os

from unittest.mock import MagicMock, patch

import pytest

from click.testing import CliRunner
from loguru import logger

from sosmed_sentiment.cli.generate_report import main, run_generate_report


def write_result(tmp_path, data):
    path = tmp_path / 'analysis_result.json'
    path.write_text(json.dumps(data), encoding='utf-8')
    return str(path)


def valid_result():
    return {
        'meta': {
            'generated_at': '2026-08-30T10:00:00', 'source_file': 'comments.json',
            'date_range': {'from': '2026-08-01', 'to': '2026-08-30'},
            'total_comments_analyzed': 1, 'total_comments_excluded_internal': 0,
            'sentiment_method_breakdown': {'lexicon': 1, 'llm': 0, 'llm_failed': 0}
        },
        'sentiment_summary': {
            'positif': 1, 'negatif': 0, 'netral': 0, 'tidak_terklasifikasi': 0,
            'positif_pct': 100.0, 'negatif_pct': 0.0, 'netral_pct': 0.0
        },
        'top_keywords_overall': [], 'top_keywords_by_sentiment': {},
        'comments': [{'username': 'user1', 'sentiment_label': 'positif', 'text_raw': 'bagus'}]
    }


def test_a_valid_input_writes_report_html_and_exits_zero(tmp_path):
    input_path = write_result(tmp_path, valid_result())
    output_path = str(tmp_path / 'report.html')

    result = CliRunner().invoke(main, ['--input', input_path, '--output', output_path])

    assert result.exit_code == 0, result.output
    assert os.path.exists(output_path)


def test_sanity_check_prints_every_tier_including_a_zero_count_one(tmp_path):
    """T-ENG-9 (explicit user requirement): the console sanity-check table
    must cover ALL tiers, including a zero-comment one - depends on
    html_builder._tier_breakdown()'s D8 fix (never omit an empty tier)."""
    data = valid_result()
    data['comments'] = [
        {
            'username': 'user1', 'sentiment_label': 'positif', 'text_raw': 'bagus',
            'video_id': 'v1', 'is_reply': False
        }
    ]
    input_path = write_result(tmp_path, data)
    comments_json_path = tmp_path / 'comments.json'
    comments_json_path.write_text(
        json.dumps([{'aweme_id': 'v1', 'account_type': 'kol account'}]), encoding='utf-8'
    )
    output_path = str(tmp_path / 'report.html')

    messages = []
    sink_id = logger.add(messages.append, format='{message}')
    try:
        result = CliRunner().invoke(main, [
            '--input', input_path, '--output', output_path,
            '--comments-json', str(comments_json_path)
        ])
    finally:
        logger.remove(sink_id)

    assert result.exit_code == 0, result.output
    joined = '\n'.join(str(m) for m in messages)
    assert 'KOL' in joined
    assert 'Official' in joined
    assert 'Affiliate' in joined
    assert 'Unknown' in joined
    assert '0 video, 0 komentar' in joined


def test_sanity_check_prints_before_the_html_file_is_written(tmp_path, monkeypatch):
    """T-ENG-9: the sanity-check table must print BEFORE handle.write(html) -
    verified by making the write itself fail and asserting the sanity-check
    log lines were already emitted despite the failure."""
    data = valid_result()
    input_path = write_result(tmp_path, data)
    output_path = str(tmp_path / 'report.html')

    messages = []
    sink_id = logger.add(messages.append, format='{message}')

    real_open = open

    def failing_open(path, *args, **kwargs):
        mode = args[0] if args else kwargs.get('mode', 'r')
        if str(path) == output_path and 'w' in mode:
            raise OSError('simulated write failure')
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr('builtins.open', failing_open)
    try:
        with pytest.raises(OSError):
            run_generate_report(input_path, output_path, None)
    finally:
        logger.remove(sink_id)

    joined = '\n'.join(str(m) for m in messages)
    assert 'Sanity check per tipe akun' in joined


def test_an_invalid_schema_exits_2_and_writes_no_partial_file(tmp_path):
    broken = valid_result()
    del broken['sentiment_summary']
    input_path = write_result(tmp_path, broken)
    output_path = str(tmp_path / 'report.html')

    result = CliRunner().invoke(main, ['--input', input_path, '--output', output_path])

    assert result.exit_code == 2
    assert not os.path.exists(output_path)


# === T8/T9/T10/T15 - narrative CLI flags ====================================

def _bigger_valid_result(classified_total=40):
    """classified_total above MIN_NARRATIVE_VOLUME (30) so the narrative
    layer actually attempts an LLM call instead of skipping straight to the
    below-volume-floor fallback (which every other fixture in this file
    intentionally sits below, since narrative generation is otherwise
    unrelated to what those tests check)."""
    data = valid_result()
    data['meta']['total_comments_analyzed'] = classified_total
    data['sentiment_summary'] = {
        'positif': classified_total, 'negatif': 0, 'netral': 0, 'tidak_terklasifikasi': 0,
        'positif_pct': 100.0, 'negatif_pct': 0.0, 'netral_pct': 0.0
    }
    data['comments'] = [
        {
            'username': 'user%d' % i, 'sentiment_label': 'positif', 'text_raw': 'bagus',
            'video_id': 'v1', 'is_reply': False, 'digg_count': 0,
            'create_time': '2026-08-01T10:00:00', 'tokens_stemmed': []
        }
        for i in range(classified_total)
    ]
    return data


def test_no_narrative_flag_skips_llm_even_with_llm_api_key_configured(tmp_path, monkeypatch):
    monkeypatch.setenv('LLM_API_KEY', 'fake-key')
    monkeypatch.setenv('LLM_MODEL', 'fake-model')
    input_path = write_result(tmp_path, _bigger_valid_result())
    output_path = str(tmp_path / 'report.html')

    with patch('sosmed_sentiment.report.llm_insights.OpenAI') as mock_openai_cls:
        result = CliRunner().invoke(main, [
            '--input', input_path, '--output', output_path, '--no-narrative'
        ])

    assert result.exit_code == 0, result.output
    assert os.path.exists(output_path)
    mock_openai_cls.assert_not_called()


def test_narrative_review_prints_banner_line_when_no_llm_configured(tmp_path, monkeypatch):
    monkeypatch.delenv('LLM_API_KEY', raising=False)
    monkeypatch.delenv('LLM_MODEL', raising=False)
    input_path = write_result(tmp_path, _bigger_valid_result())
    output_path = str(tmp_path / 'report.html')

    messages = []
    sink_id = logger.add(messages.append, format='{message}')
    try:
        result = CliRunner().invoke(main, [
            '--input', input_path, '--output', output_path, '--narrative-review'
        ])
    finally:
        logger.remove(sink_id)

    assert result.exit_code == 0, result.output
    joined = '\n'.join(str(m) for m in messages)
    assert 'no-llm-configured' in joined


def test_narrative_review_writes_sidecar_file(tmp_path, monkeypatch):
    monkeypatch.delenv('LLM_API_KEY', raising=False)
    monkeypatch.delenv('LLM_MODEL', raising=False)
    input_path = write_result(tmp_path, _bigger_valid_result())
    output_path = str(tmp_path / 'report.html')

    result = CliRunner().invoke(main, [
        '--input', input_path, '--output', output_path, '--narrative-review'
    ])

    assert result.exit_code == 0, result.output
    sidecar_path = os.path.join(os.path.dirname(output_path), 'narrative_review.json')
    assert os.path.exists(sidecar_path)
    with open(sidecar_path, encoding='utf-8') as handle:
        sidecar = json.load(handle)
    assert sidecar['reviewed_at'] is not None
    assert sidecar['reviewed_by'] is not None


def test_no_narrative_and_narrative_review_combined_prints_disabled_banner_t15(tmp_path, monkeypatch):
    """T15/Decision #21: the combined-flag behavior is defined explicitly -
    --narrative-review still prints its dump when --no-narrative is also
    set, with a banner that says the narrative was deliberately disabled
    (not click's unspecified flag precedence, not silence)."""
    monkeypatch.setenv('LLM_API_KEY', 'fake-key')
    monkeypatch.setenv('LLM_MODEL', 'fake-model')
    input_path = write_result(tmp_path, _bigger_valid_result())
    output_path = str(tmp_path / 'report.html')

    messages = []
    sink_id = logger.add(messages.append, format='{message}')
    try:
        with patch('sosmed_sentiment.report.llm_insights.OpenAI') as mock_openai_cls:
            result = CliRunner().invoke(main, [
                '--input', input_path, '--output', output_path,
                '--no-narrative', '--narrative-review'
            ])
    finally:
        logger.remove(sink_id)

    assert result.exit_code == 0, result.output
    mock_openai_cls.assert_not_called()
    joined = '\n'.join(str(m) for m in messages)
    assert 'narrative-disabled' in joined


def test_sidecar_write_failure_does_not_block_report_output(tmp_path, monkeypatch):
    monkeypatch.delenv('LLM_API_KEY', raising=False)
    monkeypatch.delenv('LLM_MODEL', raising=False)
    input_path = write_result(tmp_path, _bigger_valid_result())
    output_path = str(tmp_path / 'report.html')

    def failing_replace(*args, **kwargs):
        raise OSError('simulated disk full')

    monkeypatch.setattr('sosmed_sentiment.report.llm_insights.os.replace', failing_replace)

    result = CliRunner().invoke(main, ['--input', input_path, '--output', output_path])

    assert result.exit_code == 0, result.output
    assert os.path.exists(output_path)


def test_fresh_narrative_flag_bypasses_the_cache(tmp_path, monkeypatch):
    monkeypatch.setenv('LLM_API_KEY', 'fake-key')
    monkeypatch.setenv('LLM_MODEL', 'fake-model')
    input_path = write_result(tmp_path, _bigger_valid_result())
    output_path = str(tmp_path / 'report.html')

    narrative_json = json.dumps({
        'headline': [{'title': 'h', 'body': 'Net sentimen keseluruhan +100.0.'}],
        'risk': [{'title': 'r', 'body': 'risk body'}],
        'actions': [{'title': 'a', 'body': 'action body'}]
    })

    def fake_response():
        message = MagicMock()
        message.content = narrative_json
        choice = MagicMock()
        choice.message = message
        response = MagicMock()
        response.choices = [choice]
        return response

    with patch('sosmed_sentiment.report.llm_insights.OpenAI') as mock_openai_cls:
        client = MagicMock()
        client.chat.completions.create.return_value = fake_response()
        mock_openai_cls.return_value = client

        CliRunner().invoke(main, [
            '--input', input_path, '--output', output_path, '--fresh-narrative'
        ])
        first_call_count = client.chat.completions.create.call_count

        CliRunner().invoke(main, [
            '--input', input_path, '--output', output_path, '--fresh-narrative'
        ])
        second_call_count = client.chat.completions.create.call_count

    # --fresh-narrative on both runs -> the second run must call the LLM
    # again rather than silently reusing narrative.json's cache entry.
    assert second_call_count > first_call_count
