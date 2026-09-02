"""Inline SVG chart builders for the HTML report.

No JS, no external library, no CDN - DESIGN.md requires the report to open
correctly from a local file with no network access and to survive being
printed or screenshotted, and a charting library would break both. Every
function here returns markupsafe.Markup (raw SVG/HTML meant to be embedded
`|safe`-style into the Jinja template) - autoescape does not reach inside a
string that already carries the Markup marker, so any dynamic text embedded
in the SVG (labels, keywords, captions) is escaped explicitly with
markupsafe.escape before being interpolated. This is E-4's fix: no
hand-written esc() function, one escaping mechanism for the whole render path.
"""
import math

from typing import Any, Dict, List

from markupsafe import Markup, escape


def _svg_open(width: int, height: int, aria_label: str) -> str:
    return (
        '<svg viewBox="0 0 %d %d" width="100%%" preserveAspectRatio="xMidYMid meet" '
        'role="img" aria-label="%s">' % (width, height, escape(aria_label))
    )


def trend_chart(trend: List[Dict[str, Any]]) -> Markup:
    """Monthly volume bars (negative portion highlighted) plus a net-sentiment line.

    Reads the already-per-month `trend` rows from insights.py as-is - this
    function draws exactly the series it is given and computes no pooled or
    blended figure of its own (see insights._monthly_trend's docstring, UC-6).
    """
    if not trend:
        return Markup('<p class="chart-empty">Belum ada bulan dengan data yang cukup untuk tren.</p>')

    width, height = 860, 300
    pad_l, pad_r, pad_t, pad_b = 44, 44, 16, 40
    inner_w, inner_h = width - pad_l - pad_r, height - pad_t - pad_b
    count = len(trend)
    max_total = max(row['total'] for row in trend) or 1
    step = inner_w / count
    bar_width = step * 0.6

    def net_y(value: float) -> float:
        return pad_t + inner_h * (100 - value) / 200

    parts: List[str] = [_svg_open(width, height, 'Tren volume dan net sentimen per bulan')]

    for i in range(5):
        y = pad_t + inner_h * i / 4
        parts.append(
            '<line x1="%d" y1="%.1f" x2="%d" y2="%.1f" class="chart-grid"/>' % (
                pad_l, y, width - pad_r, y
            )
        )
    parts.append(
        '<line x1="%d" y1="%.1f" x2="%d" y2="%.1f" class="chart-zero"/>' % (
            pad_l, net_y(0), width - pad_r, net_y(0)
        )
    )

    points: List[Any] = []
    for i, row in enumerate(trend):
        x = pad_l + step * i + step / 2
        bar_h = inner_h * row['total'] / max_total
        parts.append(
            '<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" class="chart-bar">'
            '<title>%s: %d komentar</title></rect>' % (
                x - bar_width / 2, pad_t + inner_h - bar_h, bar_width, bar_h,
                escape(row['label']), row['total']
            )
        )
        neg_h = inner_h * row['neg'] / max_total
        parts.append(
            '<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" class="chart-bar-neg">'
            '<title>%s: %d negatif</title></rect>' % (
                x - bar_width / 2, pad_t + inner_h - neg_h, bar_width, neg_h,
                escape(row['label']), row['neg']
            )
        )
        parts.append(
            '<text x="%.1f" y="%d" class="chart-axis chart-axis-mid">%s</text>' % (
                x, height - pad_b + 16, escape(row['label'])
            )
        )
        points.append((x, net_y(row['net']), row))

    path = ' '.join(
        ('M' if i == 0 else 'L') + '%.1f %.1f' % (x, y) for i, (x, y, _row) in enumerate(points)
    )
    parts.append('<path d="%s" class="chart-line"/>' % path)
    for x, y, row in points:
        parts.append(
            '<circle cx="%.1f" cy="%.1f" r="3.5" class="chart-dot">'
            '<title>%s: net %+.1f</title></circle>' % (x, y, escape(row['label']), row['net'])
        )

    parts.append('</svg>')
    return Markup(''.join(parts))


def stacked_bar(pos: int, neg: int, neu: int, unk: int = 0, height: int = 14) -> Markup:
    """A single 100-wide horizontal composition bar. Renders an empty track at zero total."""
    total = pos + neg + neu + unk
    segments = [
        (pos, 'chart-seg-pos', 'Positif'),
        (neu, 'chart-seg-neu', 'Netral'),
        (neg, 'chart-seg-neg', 'Negatif'),
        (unk, 'chart-seg-unk', 'Tidak terklasifikasi')
    ]

    parts: List[str] = [
        '<svg viewBox="0 0 100 %d" preserveAspectRatio="none" class="chart-stacked-bar" '
        'role="img" aria-label="Komposisi sentimen">' % height
    ]
    if total:
        x = 0.0
        for value, css_class, name in segments:
            if not value:
                continue
            seg_width = 100.0 * value / total
            parts.append(
                '<rect x="%.3f" y="0" width="%.3f" height="%d" class="%s">'
                '<title>%s: %d (%.1f%%)</title></rect>' % (
                    x, seg_width, height, css_class, escape(name), value, seg_width
                )
            )
            x += seg_width
    parts.append('</svg>')
    return Markup(''.join(parts))


def two_segment_bar(a: int, b: int, height: int = 14) -> Markup:
    """A single 100-wide horizontal composition bar for two NON-sentiment
    values (e.g. comment vs. reply, FT-1's overview scorecard).

    Deliberately its own CSS classes (chart-seg-a/-b), not chart-seg-pos/neg
    - those colors carry sentiment meaning everywhere else in this report
    (green=positif, red=negatif) and reusing them for an unrelated split like
    comment-vs-reply would misleadingly imply a sentiment judgment where
    there isn't one (design review, fix pass 2026-09-02b, FT-1).
    """
    total = a + b
    segments = [(a, 'chart-seg-a', 'A'), (b, 'chart-seg-b', 'B')]

    parts: List[str] = [
        '<svg viewBox="0 0 100 %d" preserveAspectRatio="none" class="chart-stacked-bar" '
        'role="img" aria-label="Komposisi komentar vs balasan">' % height
    ]
    if total:
        x = 0.0
        for value, css_class, name in segments:
            if not value:
                continue
            seg_width = 100.0 * value / total
            parts.append(
                '<rect x="%.3f" y="0" width="%.3f" height="%d" class="%s">'
                '<title>%d (%.1f%%)</title></rect>' % (
                    x, seg_width, height, css_class, value, seg_width
                )
            )
            x += seg_width
    parts.append('</svg>')
    return Markup(''.join(parts))


def donut_chart(counts: Dict[str, int], net_value: float) -> Markup:
    """Sentiment distribution donut with the net score in the centre. Safe at zero total."""
    values = [
        (counts.get('positif', 0), 'chart-seg-pos', 'Positif'),
        (counts.get('netral', 0), 'chart-seg-neu', 'Netral'),
        (counts.get('negatif', 0), 'chart-seg-neg', 'Negatif'),
        (counts.get('tidak_terklasifikasi', 0), 'chart-seg-unk', 'Tidak terklasifikasi')
    ]
    total = sum(value for value, _css_class, _name in values)
    r_outer, r_inner, cx, cy = 84, 54, 100, 100

    parts: List[str] = [_svg_open(200, 200, 'Distribusi sentimen')]

    if not total:
        parts.append('<circle cx="%d" cy="%d" r="%d" class="chart-seg-unk"/>' % (cx, cy, r_outer))
    else:
        angle = -math.pi / 2
        for value, css_class, name in values:
            if not value:
                continue
            sweep = 2 * math.pi * value / total
            end_angle = angle + sweep
            large_arc = 1 if sweep > math.pi else 0
            x0, y0 = cx + r_outer * math.cos(angle), cy + r_outer * math.sin(angle)
            x1, y1 = cx + r_outer * math.cos(end_angle), cy + r_outer * math.sin(end_angle)
            xi1, yi1 = cx + r_inner * math.cos(end_angle), cy + r_inner * math.sin(end_angle)
            xi0, yi0 = cx + r_inner * math.cos(angle), cy + r_inner * math.sin(angle)
            path = (
                'M%.2f %.2f A%d %d 0 %d 1 %.2f %.2f L%.2f %.2f A%d %d 0 %d 0 %.2f %.2f Z' % (
                    x0, y0, r_outer, r_outer, large_arc, x1, y1,
                    xi1, yi1, r_inner, r_inner, large_arc, xi0, yi0
                )
            )
            pct_value = round(100.0 * value / total, 1)
            parts.append(
                '<path d="%s" class="%s"><title>%s: %d (%.1f%%)</title></path>' % (
                    path, css_class, escape(name), value, pct_value
                )
            )
            angle = end_angle

    parts.append('<text x="100" y="96" class="chart-donut-big">%+.0f</text>' % net_value)
    parts.append('<text x="100" y="116" class="chart-donut-sub">net sentimen</text>')
    parts.append('</svg>')
    return Markup(''.join(parts))


def keyword_bar_chart(rows: List[Dict[str, Any]], css_class: str) -> Markup:
    """Horizontal bars, one per distinctive keyword, sized by relative log-odds score."""
    if not rows:
        return Markup('<p class="chart-empty">Belum ada kata yang cukup khas.</p>')

    positive_scores = [row['score'] for row in rows if row['score'] > 0]
    max_score = max(positive_scores) if positive_scores else 1
    row_h, gap, label_w, count_w = 20, 6, 108, 40
    width = 320
    bar_w = width - label_w - count_w
    height = len(rows) * (row_h + gap)

    parts: List[str] = [_svg_open(width, height, 'Kata paling khas per sentimen')]
    for i, row in enumerate(rows):
        y = i * (row_h + gap)
        bar_length = max(2.0, bar_w * row['score'] / max_score) if row['score'] > 0 else 2.0
        parts.append(
            '<text x="0" y="%.1f" class="chart-kw-label">%s</text>' % (
                y + row_h * 0.7, escape(row['keyword'])
            )
        )
        parts.append(
            '<rect x="%d" y="%.1f" width="%.1f" height="%d" class="%s">'
            '<title>%s: muncul di %d komentar (%.1f%% di antaranya berlabel sentimen ini)</title>'
            '</rect>' % (
                label_w, y + 2, bar_length, row_h - 4, css_class,
                escape(row['keyword']), row['count'], row['share_pct']
            )
        )
        parts.append(
            '<text x="%d" y="%.1f" class="chart-kw-count">%d</text>' % (
                label_w + bar_w + 6, y + row_h * 0.7, row['count']
            )
        )
    parts.append('</svg>')
    return Markup(''.join(parts))
