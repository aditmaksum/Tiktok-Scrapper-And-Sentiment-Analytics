import re
import xml.etree.ElementTree as ET

from sosmed_sentiment.report import charts


def _assert_valid_svg(markup: str) -> None:
    assert markup.strip().startswith('<svg')
    ET.fromstring(markup)  # raises ParseError on malformed XML


def _assert_no_nan_or_none(markup: str) -> None:
    assert not re.search(r'\bNone\b', markup)
    assert not re.search(r'\bnan\b', markup, re.IGNORECASE)


TREND_ROW = {'label': 'Jan 26', 'total': 100, 'pos': 40, 'neg': 20, 'neu': 35, 'unk': 5, 'net': 20.0}


def test_trend_chart_with_multiple_points_is_valid_svg():
    trend = [
        TREND_ROW,
        {'label': 'Feb 26', 'total': 120, 'pos': 30, 'neg': 40, 'neu': 45, 'unk': 5, 'net': -8.3}
    ]
    svg = charts.trend_chart(trend)

    _assert_valid_svg(str(svg))
    _assert_no_nan_or_none(str(svg))


def test_trend_chart_with_one_point_does_not_crash():
    svg = charts.trend_chart([TREND_ROW])

    _assert_valid_svg(str(svg))
    _assert_no_nan_or_none(str(svg))


def test_trend_chart_with_zero_points_does_not_crash():
    svg = charts.trend_chart([])

    assert 'Belum ada' in str(svg)
    _assert_no_nan_or_none(str(svg))


def test_stacked_bar_normal_case_is_valid_svg():
    svg = charts.stacked_bar(10, 5, 8, 2)

    _assert_valid_svg(str(svg))
    _assert_no_nan_or_none(str(svg))


def test_stacked_bar_zero_total_does_not_crash_or_divide_by_zero():
    svg = charts.stacked_bar(0, 0, 0, 0)

    _assert_valid_svg(str(svg))
    _assert_no_nan_or_none(str(svg))


def test_donut_chart_with_data_is_valid_svg():
    counts = {'positif': 10, 'negatif': 5, 'netral': 8, 'tidak_terklasifikasi': 2}
    svg = charts.donut_chart(counts, 20.0)

    _assert_valid_svg(str(svg))
    _assert_no_nan_or_none(str(svg))


def test_donut_chart_degenerate_all_zero_does_not_crash():
    counts = {'positif': 0, 'negatif': 0, 'netral': 0, 'tidak_terklasifikasi': 0}
    svg = charts.donut_chart(counts, 0.0)

    _assert_valid_svg(str(svg))
    _assert_no_nan_or_none(str(svg))


def test_donut_chart_single_nonzero_segment_full_circle():
    counts = {'positif': 42, 'negatif': 0, 'netral': 0, 'tidak_terklasifikasi': 0}
    svg = charts.donut_chart(counts, 100.0)

    _assert_valid_svg(str(svg))
    _assert_no_nan_or_none(str(svg))


def test_keyword_bar_chart_with_rows_is_valid_svg_and_escapes_text():
    rows = [
        {'keyword': '<script>alert(1)</script>', 'score': 5.0, 'count': 20, 'share_pct': 60.0},
        {'keyword': 'tidak', 'score': 2.0, 'count': 15, 'share_pct': 40.0}
    ]
    svg = charts.keyword_bar_chart(rows, 'chart-kw-neg')

    _assert_valid_svg(str(svg))
    _assert_no_nan_or_none(str(svg))
    assert '<script>alert' not in str(svg)


def test_keyword_bar_chart_empty_does_not_crash():
    svg = charts.keyword_bar_chart([], 'chart-kw-neg')

    assert 'Belum ada' in str(svg)


def test_keyword_bar_chart_all_nonpositive_scores_does_not_divide_by_zero():
    rows = [{'keyword': 'x', 'score': 0.0, 'count': 15, 'share_pct': 50.0}]
    svg = charts.keyword_bar_chart(rows, 'chart-kw-neu')

    _assert_valid_svg(str(svg))
    _assert_no_nan_or_none(str(svg))
