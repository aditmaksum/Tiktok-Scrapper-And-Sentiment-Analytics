import json
import os

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
