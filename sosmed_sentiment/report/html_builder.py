import os

from collections import Counter, defaultdict
from typing import Any, Dict, List, Optional

from jinja2 import Environment, FileSystemLoader, select_autoescape

from sosmed_sentiment.errors import ReportBuildError
from sosmed_sentiment.report import charts as charts_mod
from sosmed_sentiment.report import insights as insights_mod
from tiktokcomment.sampler import TIER_ORDER, classify_tier

REQUIRED_TOP_LEVEL_FIELDS: tuple = (
    'meta', 'sentiment_summary', 'top_keywords_overall',
    'top_keywords_by_sentiment', 'comments'
)

TEMPLATE_DIR: str = os.path.join(os.path.dirname(__file__), 'templates')
SAMPLE_QUOTES_PER_LABEL: int = 5

TIER_LABELS: Dict[str, str] = {
    'kol': 'KOL', 'official': 'Official', 'affiliate': 'Affiliate', 'unknown': 'Unknown'
}
TOP_WORDS_PER_TIER: int = 15
TOP_THEMES_PER_TIER: int = 8
# A theme that only ever showed up once is a coincidence, not a theme.
MIN_THEME_COUNT: int = 2


def _mask_username(
    username: str
) -> str:
    """DESIGN.md §4: partial mask by default, e.g. 'us***ti' for privacy.

    A username of 4 chars or fewer masks everything but the first character
    - there isn't enough length left to show a first-and-last-two pattern
    without defeating the point of masking.
    """
    if not username:
        return ''
    if len(username) <= 4:
        return username[0] + '*' * (len(username) - 1)

    return username[:2] + '*' * (len(username) - 4) + username[-2:]


def _pct(
    count: int,
    total: int
) -> float:
    return round(100.0 * count / total, 1) if total else 0.0


def _account_type_of(
    comment: Dict[str, Any],
    account_type_map: Dict[str, str]
) -> str:
    video_id: str = str(comment.get('video_id') or '')
    return account_type_map.get(video_id, '')


def _tier_video_counts(
    comments: List[Dict[str, Any]],
    account_type_map: Dict[str, str]
) -> Dict[str, int]:
    """Video count per tier.

    When an account_type_map is available, this is the FULL scrape-level
    distribution (every video_id in the map, classified by tier) - not just
    the subset of videos that happen to have an analyzed comment. On the
    2026-08 run this is the difference between 460/61/54 (affiliate/kol/
    official, comments.json's full 575-video distribution) and 152/57/40
    (the smaller per_video-joined subset) - the spec's requirement #1
    ("video count") means the former, so every per-tier count in this report
    (scorecard, deep dive, CLI sanity check) must agree with it, one place.

    Falls back to counting distinct video_id values straight out of
    `comments` when no account_type_map was supplied (matches the pre-
    existing fallback behavior exactly - every comment classifies 'unknown'
    via classify_tier(''), same as before this function existed).
    """
    if account_type_map:
        counts: Counter = Counter(classify_tier(value) for value in account_type_map.values())
        return {tier: counts.get(tier, 0) for tier in TIER_ORDER}

    tiers_of_videos: Dict[str, set] = defaultdict(set)
    for comment in comments:
        video_id = comment.get('video_id')
        if not video_id:
            continue
        raw_type: str = _account_type_of(comment, account_type_map)
        tiers_of_videos[classify_tier(raw_type)].add(str(video_id))
    return {tier: len(tiers_of_videos.get(tier, set())) for tier in TIER_ORDER}


def _is_meaningful(
    comment: Dict[str, Any]
) -> bool:
    """Has text left after preprocessing, vs. an emoji-only/blank reaction.

    tokens_stemmed is what's left after clean+normalize+tokenize+stem+filter -
    empty means there was nothing to read, only react to.
    """
    return bool(comment.get('tokens_stemmed'))


def _sentiment_counts(
    comments: List[Dict[str, Any]]
) -> Dict[str, Any]:
    counts: Counter = Counter(c.get('sentiment_label', 'tidak_terklasifikasi') for c in comments)
    total: int = len(comments)

    return {
        'positif': counts.get('positif', 0),
        'negatif': counts.get('negatif', 0),
        'netral': counts.get('netral', 0),
        'positif_pct': _pct(counts.get('positif', 0), total),
        'negatif_pct': _pct(counts.get('negatif', 0), total),
        'netral_pct': _pct(counts.get('netral', 0), total)
    }


def _top_words(
    comments: List[Dict[str, Any]],
    limit: int
) -> List[Dict[str, Any]]:
    counter: Counter = Counter()
    for comment in comments:
        counter.update(comment.get('tokens_stemmed') or [])

    return [{'keyword': word, 'count': count} for word, count in counter.most_common(limit)]


def _top_themes(
    comments: List[Dict[str, Any]],
    limit: int
) -> List[Dict[str, Any]]:
    """Recurring adjacent-word pairs, as a cheap stand-in for topics.

    Not topic modelling - just the bigrams that show up more than once in
    the already-stemmed tokens. Good enough to point at what a tier keeps
    talking about without adding a new NLP step to the analyze pipeline.
    """
    counter: Counter = Counter()
    for comment in comments:
        tokens: List[str] = comment.get('tokens_stemmed') or []
        for first, second in zip(tokens, tokens[1:]):
            counter['%s %s' % (first, second)] += 1

    return [
        {'theme': theme, 'count': count}
        for theme, count in counter.most_common(limit)
        if count >= MIN_THEME_COUNT
    ]


def _tier_breakdown(
    comments: List[Dict[str, Any]],
    account_type_map: Dict[str, str]
) -> List[Dict[str, Any]]:
    """Per-tier (KOL/Official/Affiliate/Unknown) stats for the report sections.

    Grouped with the same classify_tier() the sampler and batch runner use,
    so a tier here means the same thing it means everywhere else in this
    tool.

    T-ENG-6/D8 (CRITICAL regression fix, fix pass 2026-09-02c): every tier in
    TIER_ORDER is always returned, including one with zero comments, as a
    zero-value dict - never omitted. The prior "if not group: continue" skip
    silently dropped a genuinely-empty tier from both this scorecard and (had
    it been reused unchanged) the new per-account-type deep dive, which
    depends on the unknown/"Tidak diketahui" bucket always being present even
    at zero count. One function, one behavior, no parallel path that could
    drift.
    """
    tiers: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for comment in comments:
        raw_type: str = _account_type_of(comment, account_type_map)
        tiers[classify_tier(raw_type)].append(comment)

    keywords_by_tier: Dict[str, List[Dict[str, Any]]] = insights_mod._distinctive_keywords_by_tier(
        tiers
    )
    video_counts: Dict[str, int] = _tier_video_counts(comments, account_type_map)

    result: List[Dict[str, Any]] = []
    for tier in TIER_ORDER:
        group: List[Dict[str, Any]] = tiers.get(tier) or []

        total: int = len(group)
        top_level: List[Dict[str, Any]] = [c for c in group if not c.get('is_reply')]
        replies: List[Dict[str, Any]] = [c for c in group if c.get('is_reply')]
        meaningful: int = sum(1 for c in group if _is_meaningful(c))
        noise: int = total - meaningful
        sentiment_summary: Dict[str, Any] = _sentiment_counts(group)
        # FT-1 scorecard: route through insights.py's one canonical
        # net_score()/classified_base() rather than hand-rolling a second net
        # computation here (insights.py's classified_base docstring is
        # explicit that every net figure in the report must share this one
        # denominator - a tier scorecard is no exception).
        tier_base: int = insights_mod.classified_base(sentiment_summary)
        tier_net: float = insights_mod.net_score(
            sentiment_summary['positif'], sentiment_summary['negatif'], tier_base
        )

        result.append({
            'tier': tier,
            'label': TIER_LABELS.get(tier, tier.title()),
            'video_count': video_counts.get(tier, 0),
            'total_count': total,
            'comment_count': len(top_level),
            'reply_count': len(replies),
            'meaningful_count': meaningful,
            'meaningful_pct': _pct(meaningful, total),
            'noise_count': noise,
            'noise_pct': _pct(noise, total),
            'sentiment_summary': sentiment_summary,
            'net': tier_net,
            'keywords_distinctive': keywords_by_tier.get(tier, []),
            'top_words': _top_words(group, TOP_WORDS_PER_TIER),
            'top_themes': _top_themes(group, TOP_THEMES_PER_TIER)
        })

    return result


def _overall_summary(
    comments: List[Dict[str, Any]],
    account_type_map: Dict[str, str]
) -> Dict[str, Any]:
    """Top-of-report numbers: per-tier video/comment counts, comment vs. reply.

    T-ENG-6/D8: every tier in TIER_ORDER is always included, even one with
    zero comments - same fix and same reasoning as _tier_breakdown() above,
    applied here too so the two functions cannot silently diverge again.
    """
    tiers: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for comment in comments:
        raw_type: str = _account_type_of(comment, account_type_map)
        tiers[classify_tier(raw_type)].append(comment)

    video_counts: Dict[str, int] = _tier_video_counts(comments, account_type_map)

    by_tier: List[Dict[str, Any]] = []
    for tier in TIER_ORDER:
        group: List[Dict[str, Any]] = tiers.get(tier) or []

        by_tier.append({
            'tier': tier,
            'label': TIER_LABELS.get(tier, tier.title()),
            'video_count': video_counts.get(tier, 0),
            'comment_count': len(group)
        })

    total: int = len(comments)
    top_level: int = sum(1 for c in comments if not c.get('is_reply'))
    reply: int = total - top_level

    return {
        'by_tier': by_tier,
        'comment_vs_reply': {
            'comment': top_level,
            'reply': reply,
            'comment_pct': _pct(top_level, total),
            'reply_pct': _pct(reply, total)
        }
    }


def _sample_quotes(
    comments: List[Dict[str, Any]]
) -> Dict[str, List[Dict[str, str]]]:
    by_label: Dict[str, List[Dict[str, str]]] = {}

    for comment in comments:
        label: str = comment['sentiment_label']
        bucket = by_label.setdefault(label, [])
        if len(bucket) < SAMPLE_QUOTES_PER_LABEL:
            bucket.append({
                'masked_username': _mask_username(comment['username']),
                'text_raw': comment['text_raw']
            })

    return by_label


def _mask_top_comments(
    top_comments: Dict[str, List[Dict[str, Any]]]
) -> Dict[str, List[Dict[str, Any]]]:
    """Replace raw usernames with the DESIGN.md §4 masked form before rendering.

    insights.py stays privacy-agnostic (it is the pure-metrics layer); masking
    is a rendering concern, same as _sample_quotes already treats it below.
    """
    return {
        label: [
            {**comment, 'username': _mask_username(comment['username'])}
            for comment in comments
        ]
        for label, comments in top_comments.items()
    }


def _attach_video_bars(
    video_leaderboard: Dict[str, Any]
) -> Dict[str, Any]:
    """Add a rendered stacked-bar SVG to each leaderboard row, once, here.

    Keeps insights.py free of any rendering concern (SVG is charts.py's job)
    while avoiding a second SVG-building call site inside the template itself.
    """
    result: Dict[str, Any] = dict(video_leaderboard)
    for key in ('best', 'worst', 'loudest'):
        result[key] = [
            {**video, 'bar': charts_mod.stacked_bar(video['pos'], video['neg'], video['neu'], height=10)}
            for video in video_leaderboard.get(key, [])
        ]
    return result


def _mask_tier_examples(
    tier_rows: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """Mask example-comment usernames before render (T-ENG-8).

    A new call site for insights._build_tier_deep_dive()'s output, parallel
    to _mask_top_comments() above rather than an edit to it - the two mask
    different shapes of data (a label-keyed dict there, a list of tier rows
    here) and _mask_top_comments() itself must keep passing its own existing
    tests unmodified.
    """
    result: List[Dict[str, Any]] = []
    for tier in tier_rows:
        masked = dict(tier)
        masked['examples'] = [
            {**comment, 'username': _mask_username(comment['username'])}
            for comment in tier['examples']
        ]
        result.append(masked)
    return result


def _attach_tier_deep_dive_charts(
    tier_rows: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """Add the composition bar + distinctive-keyword bar SVGs to each tier row.

    Same one-call-site-per-chart-type discipline as _attach_video_bars() and
    _build_charts() above - insights.py stays free of any rendering concern.
    """
    result: List[Dict[str, Any]] = []
    for tier in tier_rows:
        row = dict(tier)
        counts = tier['sentiment_counts']
        row['composition_bar'] = charts_mod.stacked_bar(
            counts['positif'], counts['negatif'], counts['netral'], counts['tidak_terklasifikasi'],
            height=16
        )
        row['keywords_bar'] = charts_mod.keyword_bar_chart(
            tier['keywords'], 'chart-kw-tier-%s' % tier['tier']
        )
        result.append(row)
    return result


def _tier_deep_dive(
    comments: List[Dict[str, Any]],
    account_type_map: Dict[str, str]
) -> List[Dict[str, Any]]:
    """Per-account-type deep dive (fix pass 2026-09-02c): one block each for
    kol/official/affiliate/unknown ("Tidak diketahui"), ordered by comment
    volume descending (TD-8), ALWAYS all four (D8) - never omitted, even a
    tier with zero comments on this dataset.

    Tiering happens here (classify_tier), not in insights.py (T-ENG-2) - the
    resulting comments_by_tier dict is hand-built the same way _tier_breakdown()
    and _overall_summary() above already build one, so all three share one
    grouping convention.
    """
    tiers: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for comment in comments:
        raw_type: str = _account_type_of(comment, account_type_map)
        tiers[classify_tier(raw_type)].append(comment)

    video_counts: Dict[str, int] = _tier_video_counts(comments, account_type_map)

    # video_counts is passed in (not patched onto the rows afterward) so the
    # per-tier narrative sentences - built inside _build_tier_deep_dive,
    # before this function ever sees the rows - cite the same video count as
    # the KPI strip, matching _tier_breakdown()'s fix above (T-ENG-6).
    rows: List[Dict[str, Any]] = insights_mod._build_tier_deep_dive(tiers, video_counts=video_counts)
    rows = _mask_tier_examples(rows)
    rows = _attach_tier_deep_dive_charts(rows)
    return rows


def _build_charts(
    metrics: Dict[str, Any]
) -> Dict[str, Any]:
    """One call site for every SVG the report needs, built from the metrics dict."""
    counts = metrics['sentiment_counts']
    keywords = metrics['keywords_distinctive']

    return {
        'trend': charts_mod.trend_chart(metrics['trend']),
        'donut': charts_mod.donut_chart(counts, metrics['net_overall']),
        'sentiment_bar': charts_mod.stacked_bar(
            counts['positif'], counts['negatif'], counts['netral'], counts['tidak_terklasifikasi'],
            height=18
        ),
        'keywords_positif': charts_mod.keyword_bar_chart(keywords['positif'], 'chart-kw-pos'),
        'keywords_negatif': charts_mod.keyword_bar_chart(keywords['negatif'], 'chart-kw-neg'),
        'keywords_netral': charts_mod.keyword_bar_chart(keywords['netral'], 'chart-kw-neu')
    }


def build_tier_summary(
    data: Dict[str, Any],
    account_type_map: Optional[Dict[str, str]] = None
) -> List[Dict[str, Any]]:
    """Public wrapper over _tier_breakdown(), for cli/generate_report.py's
    console sanity-check table (T-ENG-9) - the CLI needs per-tier net/video/
    comment counts before the HTML is written, without duplicating the
    tiering logic or importing a private (underscore-prefixed) function
    across module boundaries.
    """
    comments: List[Dict[str, Any]] = data.get('comments') or []
    return _tier_breakdown(comments, account_type_map or {})


def _validate(
    data: Dict[str, Any]
) -> None:
    missing: List[str] = [field for field in REQUIRED_TOP_LEVEL_FIELDS if field not in data]
    if missing:
        raise ReportBuildError(
            'analysis_result.json missing required field(s): %s' % ', '.join(missing)
        )


def build_report(
    data: Dict[str, Any],
    template_dir: str = TEMPLATE_DIR,
    template_name: str = 'report.html.j2',
    account_type_map: Optional[Dict[str, str]] = None,
    total_population_videos: Optional[int] = None,
    narrative_override: Optional[Dict[str, Any]] = None
) -> str:
    """analysis_result.json (already parsed) -> rendered HTML string.

    Raises ReportBuildError on a schema violation - never returns a partial
    or empty-looking HTML for invalid input (PRD.md FR-07 kriteria gagal).

    template_dir/template_name let cli.generate_report's --template flag
    point at an analyst-supplied template without duplicating everything
    else this function does to build the render context.

    account_type_map (video_id -> account_type) drives the per-tier
    breakdown. It comes from the source comments.json, not from
    analysis_result.json itself - when it's empty (file missing, or every
    comment predates the fix that carries video_id), every tier section is
    simply left out rather than shown wrong.

    total_population_videos (FT-2): operator-supplied estimate of the
    account's total video count, threaded straight through to
    insights.build_metrics() for the demoted trend caveat. None by default.

    narrative_override (docs/plans/2026-09-04-llm-narrative-citation-
    guardrail.md, Eng phase Section 1 diagram): when given, replaces
    metrics['narrative'] (insights.build_narrative()'s deterministic result)
    BEFORE the template renders - the point where cli.generate_report.py's
    llm_insights.generate_narrative_with_guardrail() result (LLM-accepted or
    its own deterministic fallback) reaches the report. This ordering is
    part of the contract: it must happen after build_metrics() computes the
    deterministic narrative (so the fallback value below stays available)
    and before template.render() reads metrics['narrative'] - a future edit
    that reorders these two calls would silently ship a report whose
    narrative was never LLM-attempted at all. None by default (unchanged
    behavior: metrics['narrative'] stays build_narrative()'s own result).
    """
    _validate(data)

    meta: Dict[str, Any] = data['meta']
    total_analyzed: int = meta['total_comments_analyzed']
    breakdown: Dict[str, int] = meta['sentiment_method_breakdown']
    escalated: int = breakdown.get('llm', 0) + breakdown.get('llm_failed', 0)
    llm_escalation_pct: float = round(100.0 * escalated / total_analyzed, 1) if total_analyzed else 0.0

    comments: List[Dict[str, Any]] = data['comments']
    account_type_map = account_type_map or {}

    total_videos: int = meta.get('total_videos')
    if total_videos is None:
        total_videos = len({c['video_id'] for c in comments if c.get('video_id')})

    metrics: Dict[str, Any] = insights_mod.build_metrics(data, total_population_videos)
    if narrative_override is not None:
        metrics['narrative'] = narrative_override
    metrics['top_comments'] = _mask_top_comments(metrics['top_comments'])
    metrics['video_leaderboard'] = _attach_video_bars(metrics['video_leaderboard'])
    charts: Dict[str, Any] = _build_charts(metrics)
    overall_summary: Dict[str, Any] = _overall_summary(comments, account_type_map)
    charts['comment_vs_reply_bar'] = charts_mod.two_segment_bar(
        overall_summary['comment_vs_reply']['comment'], overall_summary['comment_vs_reply']['reply']
    )

    env = Environment(
        loader=FileSystemLoader(template_dir),
        autoescape=select_autoescape(['html', 'j2'])
    )
    template = env.get_template(template_name)

    return template.render(
        run_id=meta.get('run_id', ''),
        generated_at=meta['generated_at'],
        source_file=meta['source_file'],
        date_from=meta['date_range']['from'],
        date_to=meta['date_range']['to'],
        total_videos=total_videos,
        total_comments_raw=meta.get('total_comments_raw', total_analyzed),
        total_comments_analyzed=total_analyzed,
        total_comments_excluded_internal=meta['total_comments_excluded_internal'],
        sentiment_summary=data['sentiment_summary'],
        sentiment_method_breakdown=breakdown,
        llm_escalation_pct=llm_escalation_pct,
        top_keywords_overall=data['top_keywords_overall'],
        top_keywords_by_sentiment=data['top_keywords_by_sentiment'],
        sample_quotes=_sample_quotes(comments),
        excluded_accounts_detected=data.get('excluded_accounts_detected', []),
        overall_summary=overall_summary,
        tier_breakdown=_tier_breakdown(comments, account_type_map),
        tier_deep_dive=_tier_deep_dive(comments, account_type_map),
        metrics=metrics,
        charts=charts,
        min_month_volume=insights_mod.MIN_MONTH_VOLUME,
        min_video_comments=insights_mod.MIN_VIDEO_COMMENTS,
        explorer_row_cap=insights_mod.EXPLORER_ROW_CAP
    )
