import json
import os

from click.testing import CliRunner

from sosmed_sentiment.cli.generate_report import main


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


def test_an_invalid_schema_exits_2_and_writes_no_partial_file(tmp_path):
    broken = valid_result()
    del broken['sentiment_summary']
    input_path = write_result(tmp_path, broken)
    output_path = str(tmp_path / 'report.html')

    result = CliRunner().invoke(main, ['--input', input_path, '--output', output_path])

    assert result.exit_code == 2
    assert not os.path.exists(output_path)
