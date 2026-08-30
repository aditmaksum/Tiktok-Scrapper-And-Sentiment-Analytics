import pytest

from sosmed_sentiment.errors import ReportBuildError
from sosmed_sentiment.report.html_builder import _mask_username, build_report


def valid_result(total_analyzed=2, comments=None):
    return {
        'meta': {
            'generated_at': '2026-08-30T10:00:00',
            'source_file': 'comments.json',
            'date_range': {'from': '2026-08-01', 'to': '2026-08-30'},
            'total_comments_analyzed': total_analyzed,
            'total_comments_excluded_internal': 0,
            'sentiment_method_breakdown': {'lexicon': total_analyzed, 'llm': 0, 'llm_failed': 0}
        },
        'sentiment_summary': {
            'positif': 1, 'negatif': 1, 'netral': 0, 'tidak_terklasifikasi': 0,
            'positif_pct': 50.0, 'negatif_pct': 50.0, 'netral_pct': 0.0
        },
        'top_keywords_overall': [{'keyword': 'bagus', 'score': 0.5, 'count': 3}],
        'top_keywords_by_sentiment': {'positif': [], 'negatif': [], 'netral': []},
        'comments': comments if comments is not None else [
            {'username': 'user1', 'sentiment_label': 'positif', 'text_raw': 'bagus'},
            {'username': 'user2', 'sentiment_label': 'negatif', 'text_raw': 'jelek'}
        ]
    }


def test_a_valid_result_renders_html_with_the_methodology_block():
    html = build_report(valid_result())

    assert '<html' in html
    assert 'Metodologi' in html


def test_zero_comments_shows_the_explicit_empty_message():
    html = build_report(valid_result(total_analyzed=0, comments=[]))

    assert 'Tidak ada komentar untuk dianalisis' in html


def test_missing_required_field_raises_report_build_error():
    broken = valid_result()
    del broken['sentiment_summary']

    with pytest.raises(ReportBuildError):
        build_report(broken)


def test_all_llm_failed_shows_the_warning():
    data = valid_result()
    data['meta']['sentiment_method_breakdown'] = {'lexicon': 0, 'llm': 0, 'llm_failed': 2}

    html = build_report(data)

    assert 'Peringatan' in html


def test_mask_username_keeps_first_and_last_two_characters():
    assert _mask_username('username123') == 'us*******23'


def test_mask_username_handles_short_usernames():
    assert _mask_username('abc') == 'a**'


def test_mask_username_handles_empty_string():
    assert _mask_username('') == ''


def test_excluded_accounts_detected_renders_when_present():
    data = valid_result()
    data['excluded_accounts_detected'] = [
        {'username': 'yaylesupport', 'total_muncul': 12, 'alasan': 'internal_account'}
    ]

    html = build_report(data)

    assert 'yaylesupport' in html
    assert 'Transparansi Data' in html


def test_transparency_section_is_omitted_when_empty():
    html = build_report(valid_result())

    assert 'Transparansi Data' not in html
