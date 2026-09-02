import pytest

from sosmed_sentiment.errors import ReportBuildError
from sosmed_sentiment.report.html_builder import _mask_username, build_report, build_tier_summary


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


def test_scorecard_section_is_omitted_when_there_are_no_comments():
    """FT-1: _tier_breakdown()/`_overall_summary()`'s by_tier never return
    None (classify_tier('') resolves to 'unknown', confirmed by reading
    tiktokcomment/sampler.py:39-56) - they return an empty list only when
    there are genuinely zero comments to classify. That's the one case the
    {% if %} guard must actually catch, matching the excluded_accounts_detected
    pattern: an absent section, not a table with headers and zero rows."""
    html = build_report(valid_result(total_analyzed=0, comments=[]))

    assert 'Siapa yang berbicara' not in html


def test_scorecard_section_falls_back_to_unknown_tier_without_account_type_map():
    """Without an account_type_map, every comment classifies as tier
    'unknown' (classify_tier('') -> 'unknown', never None) - the scorecard
    still renders, with a single 'Unknown' row, rather than being omitted."""
    html = build_report(valid_result())

    assert 'Siapa yang berbicara' in html
    assert 'Unknown' in html


def test_scorecard_section_renders_when_account_type_map_present():
    data = valid_result(comments=[
        {
            'username': 'user1', 'sentiment_label': 'positif', 'text_raw': 'bagus',
            'video_id': 'v1', 'is_reply': False
        },
        {
            'username': 'user2', 'sentiment_label': 'negatif', 'text_raw': 'jelek',
            'video_id': 'v1', 'is_reply': True
        }
    ])

    html = build_report(data, account_type_map={'v1': 'kol'})

    assert 'Siapa yang berbicara' in html
    assert 'Per tipe akun' in html
    assert 'KOL' in html


def test_tier_breakdown_includes_a_genuinely_empty_tier_as_a_zero_row():
    """CRITICAL regression (T-ENG-6/D8): with an account_type_map that only
    ever resolves to 'kol', 'official'/'affiliate'/'unknown' still must
    appear in build_tier_summary()'s result as zero-value rows - the
    pre-fix `if not group: continue` skip would have silently dropped them.
    """
    data = valid_result(comments=[
        {
            'username': 'user1', 'sentiment_label': 'positif', 'text_raw': 'bagus',
            'video_id': 'v1', 'is_reply': False
        }
    ])

    rows = build_tier_summary(data, account_type_map={'v1': 'kol account'})
    tiers_present = {row['tier'] for row in rows}

    assert tiers_present == {'kol', 'official', 'affiliate', 'unknown'}
    official_row = next(row for row in rows if row['tier'] == 'official')
    assert official_row['video_count'] == 0
    assert official_row['comment_count'] == 0
    assert official_row['net'] == 0.0


def test_tier_deep_dive_example_comment_usernames_are_masked():
    """T-ENG-8: the deep dive's example-comment usernames must route through
    _mask_username() before render, same as _mask_top_comments() does for
    the existing top-comments section - a raw username must never appear."""
    data = valid_result(comments=[
        {
            'username': 'unmaskeduser', 'sentiment_label': 'positif', 'text_raw': 'bagus banget',
            'video_id': 'v1', 'is_reply': False, 'digg_count': 5,
            'tokens_stemmed': ['bagus', 'banget']
        }
    ])

    html = build_report(data, account_type_map={'v1': 'kol account'})

    assert 'unmaskeduser' not in html
