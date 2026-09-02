import json
import math
import os
import re

import pytest

from sosmed_sentiment.report import insights
from sosmed_sentiment.report.html_builder import build_report

REAL_ANALYSIS_RESULT = os.path.join(
    os.path.dirname(__file__), '..', '..', '..', 'runs', '2026-08', 'analysis_result.json'
)

REQUIRED_SECTION_IDS = (
    'ringkasan', 'tipe-akun', 'risiko', 'aksi', 'tren', 'kata-pembeda',
    'video', 'suara', 'kualitas-data', 'jelajah'
)


def _assert_no_stray_none(html: str) -> None:
    assert not re.search(r'\bNone\b', html)


def _assert_no_nan_in_metrics(value) -> None:
    """Recursively check insights.build_metrics()'s output for a stray NaN.

    Checking the *metrics dict* rather than grepping the rendered HTML for
    "nan": real TikTok comment text legitimately contains the standalone
    Indonesian word "nan" (informal contraction of "kan"), which makes a
    substring/word-boundary search on the full page unreliable on real data.
    Every number this report prints comes from this dict, so checking it here
    covers the same risk without that false-positive.
    """
    if isinstance(value, float):
        assert not math.isnan(value)
    elif isinstance(value, dict):
        for item in value.values():
            _assert_no_nan_in_metrics(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _assert_no_nan_in_metrics(item)


def _small_synthetic_result():
    """Below every noise floor (MIN_MONTH_VOLUME, MIN_VIDEO_COMMENTS) on purpose -
    the edge case where every analytic section degrades to its empty state
    rather than crashing or fabricating a ranking from too little data."""
    return {
        'meta': {
            'run_id': 'run-test-small',
            'generated_at': '2026-09-02T10:00:00',
            'source_file': 'comments.json',
            'date_range': {'from': '2026-08-01', 'to': '2026-08-02'},
            'total_comments_analyzed': 3,
            'total_comments_excluded_internal': 0,
            'sentiment_method_breakdown': {'model': 3, 'llm': 0, 'llm_failed': 0}
        },
        'sentiment_summary': {
            'positif': 1, 'negatif': 1, 'netral': 1, 'tidak_terklasifikasi': 0,
            'positif_pct': 33.3, 'negatif_pct': 33.3, 'netral_pct': 33.3
        },
        'top_keywords_overall': [],
        'top_keywords_by_sentiment': {'positif': [], 'negatif': [], 'netral': []},
        'comments': [
            {
                'comment_id': '1', 'video_id': 'v1', 'is_reply': False,
                'username': 'user1', 'text_raw': 'bagus', 'text_clean': 'bagus',
                'tokens_stemmed': ['bagus'], 'sentiment_label': 'positif',
                'sentiment_confidence': 0.9, 'sentiment_method': 'model',
                'create_time': '2026-08-01T10:00:00', 'digg_count': 1
            },
            {
                'comment_id': '2', 'video_id': 'v1', 'is_reply': False,
                'username': 'user2', 'text_raw': 'jelek', 'text_clean': 'jelek',
                'tokens_stemmed': ['jelek'], 'sentiment_label': 'negatif',
                'sentiment_confidence': 0.9, 'sentiment_method': 'model',
                'create_time': '2026-08-01T11:00:00', 'digg_count': 0
            },
            {
                'comment_id': '3', 'video_id': 'v1', 'is_reply': False,
                'username': 'user3', 'text_raw': 'tanya dong', 'text_clean': 'tanya dong',
                'tokens_stemmed': ['tanya'], 'sentiment_label': 'netral',
                'sentiment_confidence': 0.9, 'sentiment_method': 'model',
                'create_time': '2026-08-02T09:00:00', 'digg_count': 0
            }
        ]
    }


def test_small_synthetic_dataset_renders_without_crashing():
    data = _small_synthetic_result()
    html = build_report(data)

    assert '<html' in html
    for section_id in REQUIRED_SECTION_IDS:
        assert 'id="%s"' % section_id in html
    _assert_no_stray_none(html)
    _assert_no_nan_in_metrics(insights.build_metrics(data))


def test_print_color_adjust_is_present_for_print_survival():
    """Fix #7: without this, printed/screenshotted output drops the sentiment
    fills (donut, stacked bars, tags) - a verified defect in the reference."""
    html = build_report(_small_synthetic_result())

    assert '@media print' in html
    assert 'print-color-adjust: exact' in html


@pytest.mark.skipif(
    not os.path.exists(REAL_ANALYSIS_RESULT),
    reason='runs/2026-08/analysis_result.json not present in this checkout'
)
def test_real_dataset_end_to_end_has_every_section_and_no_stray_none_or_nan():
    with open(REAL_ANALYSIS_RESULT, encoding='utf-8') as handle:
        data = json.load(handle)

    html = build_report(data)

    assert '<html' in html
    for section_id in REQUIRED_SECTION_IDS:
        assert 'id="%s"' % section_id in html
    _assert_no_stray_none(html)
    _assert_no_nan_in_metrics(insights.build_metrics(data))
    assert '@media print' in html
    assert 'print-color-adjust: exact' in html


@pytest.mark.skipif(
    not os.path.exists(REAL_ANALYSIS_RESULT),
    reason='runs/2026-08/analysis_result.json not present in this checkout'
)
def test_real_dataset_kpi_row_and_denominator_disclosure_present():
    with open(REAL_ANALYSIS_RESULT, encoding='utf-8') as handle:
        data = json.load(handle)

    html = build_report(data)

    assert 'class="kpis"' in html
    assert 'Net sentimen dan seluruh angka turunannya' in html


def _tier_fixture_result():
    """Every comment's video_id maps to kol/official (never affiliate, never
    unmapped) - a deliberately-empty 'unknown'/'affiliate' tier alongside
    non-empty ones, so the CRITICAL regression (a genuinely zero-count tier
    must still render, never be silently omitted) can be tested without
    depending on runs/2026-08/analysis_result.json being present.
    """
    comments = []
    for i in range(insights.MIN_KEYWORD_DOC_COUNT + 3):
        comments.append({
            'comment_id': 'kol-%d' % i, 'video_id': 'vkol', 'is_reply': False,
            'username': 'kolwatcher%d' % i, 'text_raw': 'suka banget produk ini bunda',
            'tokens_stemmed': ['suka', 'produk', 'bunda'], 'sentiment_label': 'positif',
            'sentiment_confidence': 0.9, 'sentiment_method': 'model',
            'create_time': '2026-08-01T10:00:00', 'digg_count': 100 - i
        })
    for i in range(insights.MIN_KEYWORD_DOC_COUNT + 3):
        comments.append({
            'comment_id': 'off-%d' % i, 'video_id': 'voff', 'is_reply': False,
            'username': 'offreader%d' % i, 'text_raw': 'harga berapa ya dan aman ga',
            'tokens_stemmed': ['harga', 'aman'], 'sentiment_label': 'netral',
            'sentiment_confidence': 0.9, 'sentiment_method': 'model',
            'create_time': '2026-08-01T11:00:00', 'digg_count': 50 - i
        })

    data = {
        'meta': {
            'run_id': 'run-test-tier',
            'generated_at': '2026-09-02T10:00:00',
            'source_file': 'comments.json',
            'date_range': {'from': '2026-08-01', 'to': '2026-08-02'},
            'total_comments_analyzed': len(comments),
            'total_comments_excluded_internal': 0,
            'sentiment_method_breakdown': {'model': len(comments), 'llm': 0, 'llm_failed': 0}
        },
        'sentiment_summary': {
            'positif': insights.MIN_KEYWORD_DOC_COUNT + 3, 'negatif': 0,
            'netral': insights.MIN_KEYWORD_DOC_COUNT + 3, 'tidak_terklasifikasi': 0,
            'positif_pct': 50.0, 'negatif_pct': 0.0, 'netral_pct': 50.0
        },
        'top_keywords_overall': [],
        'top_keywords_by_sentiment': {'positif': [], 'negatif': [], 'netral': []},
        'comments': comments
    }
    account_type_map = {'vkol': 'kol account', 'voff': 'official account'}
    return data, account_type_map


def test_zero_count_tier_is_never_omitted_from_the_deep_dive():
    """CRITICAL regression (T-ENG-6/D8, fix pass 2026-09-02c): a tier with
    genuinely zero comments (affiliate and unknown, in this fixture) must
    still render its block header and empty-state copy - never be silently
    dropped the way the pre-fix `if not group: continue` skip did.
    """
    data, account_type_map = _tier_fixture_result()
    html = build_report(data, account_type_map=account_type_map)

    assert 'id="tipe-affiliate"' in html
    assert 'id="tipe-unknown"' in html
    assert 'Tidak diketahui' in html
    assert 'Tidak ada komentar tanpa tipe akun teridentifikasi.' in html


def test_deep_dive_renders_all_seven_requirements_for_nonempty_tiers():
    """Requirements #1-#7 (fix pass 2026-09-02c spec): video/comment counts,
    sentiment composition, net sentiment, dominant themes, distinctive
    keywords, masked example comments, and narrative sentences must all be
    present in the rendered HTML for a tier that actually has data.
    """
    data, account_type_map = _tier_fixture_result()
    html = build_report(data, account_type_map=account_type_map)

    kol_block = html[html.index('id="tipe-kol"'):html.index('id="tipe-official"')]

    # #1 video/comment counts + % of total
    assert 'dari seluruh komentar' in kol_block
    # #2/#3 sentiment composition + net sentiment
    assert 'Net sentimen' in kol_block
    assert 'Komposisi sentimen' in kol_block
    # #4 dominant themes (label text, not just the raw theme key)
    assert 'Dosis' in kol_block or 'cara pakai' in kol_block or 'Tema dominan' in kol_block
    # #5 distinctive keywords chart (SVG bar chart markup)
    assert '<svg' in kol_block
    # #6 masked example comments - real username never appears unmasked
    assert 'kolwatcher0' not in kol_block
    assert 'class="q ' in kol_block
    # #7 narrative sentences
    assert '<h3>Insight</h3>' in kol_block


@pytest.mark.skipif(
    not os.path.exists(REAL_ANALYSIS_RESULT),
    reason='runs/2026-08/analysis_result.json not present in this checkout'
)
def test_real_dataset_deep_dive_ordered_by_comment_volume_descending():
    """TD-8: the four tier-deep-dive blocks are ordered by comment volume
    descending, not TIER_ORDER's fixed enum order. On the real 2026-08
    dataset that means kol (3.621 comments) before affiliate (2.798) before
    official (2.056), even though affiliate has far more videos.
    """
    with open(REAL_ANALYSIS_RESULT, encoding='utf-8') as handle:
        data = json.load(handle)
    comments_json_path = os.path.join(os.path.dirname(REAL_ANALYSIS_RESULT), 'comments.json')
    account_type_map = {}
    if os.path.exists(comments_json_path):
        with open(comments_json_path, encoding='utf-8') as handle:
            raw = json.load(handle)
        account_type_map = {
            str(video['aweme_id']): (video.get('account_type') or 'unknown')
            for video in raw if isinstance(video, dict) and video.get('aweme_id')
        }

    html = build_report(data, account_type_map=account_type_map)

    order = sorted(
        (html.index('id="tipe-kol"'), html.index('id="tipe-affiliate"'), html.index('id="tipe-official"'))
    )
    assert order == [
        html.index('id="tipe-kol"'), html.index('id="tipe-affiliate"'), html.index('id="tipe-official"')
    ]


@pytest.mark.skipif(
    not os.path.exists(REAL_ANALYSIS_RESULT),
    reason='runs/2026-08/analysis_result.json not present in this checkout'
)
def test_real_dataset_explorer_is_server_rendered_and_capped():
    """TD-4: rows must be in the HTML itself, not only in a JS payload -
    the reference shipped an empty <div id="rows"> filled only by JS."""
    with open(REAL_ANALYSIS_RESULT, encoding='utf-8') as handle:
        data = json.load(handle)

    html = build_report(data)
    row_count = html.count('class="explorer-row"')

    assert 1 <= row_count <= 150
    assert 'aria-pressed' in html
    assert '<button' in html
