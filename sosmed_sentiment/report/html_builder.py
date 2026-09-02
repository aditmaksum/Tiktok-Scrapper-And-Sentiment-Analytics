import os

from collections import Counter, defaultdict
from typing import Any, Dict, List, Optional

from jinja2 import Environment, FileSystemLoader, select_autoescape

from sosmed_sentiment.errors import ReportBuildError
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
TOP_KEYWORDS_PER_TIER_SENTIMENT: int = 10
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


def _top_keywords_by_sentiment_local(
    comments: List[Dict[str, Any]],
    limit: int
) -> Dict[str, List[Dict[str, Any]]]:
    """Same shape as top_keywords_overall, but a plain word-frequency count.

    Not TF-IDF - re-running scikit-learn's vectorizer per account-type tier
    would mean touching the analyze pipeline. A frequency count over the
    tokens the pipeline already stemmed is enough to show what each tier's
    sentiment buckets are actually saying.
    """
    buckets: Dict[str, Counter] = defaultdict(Counter)
    for comment in comments:
        label: str = comment.get('sentiment_label', 'tidak_terklasifikasi')
        buckets[label].update(comment.get('tokens_stemmed') or [])

    return {
        label: [{'keyword': word, 'count': count} for word, count in counter.most_common(limit)]
        for label, counter in buckets.items()
    }


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
    tool. A tier with zero comments is left out rather than rendered empty.
    """
    tiers: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for comment in comments:
        raw_type: str = _account_type_of(comment, account_type_map)
        tiers[classify_tier(raw_type)].append(comment)

    result: List[Dict[str, Any]] = []
    for tier in TIER_ORDER:
        group: List[Dict[str, Any]] = tiers.get(tier) or []
        if not group:
            continue

        total: int = len(group)
        top_level: List[Dict[str, Any]] = [c for c in group if not c.get('is_reply')]
        replies: List[Dict[str, Any]] = [c for c in group if c.get('is_reply')]
        meaningful: int = sum(1 for c in group if _is_meaningful(c))
        noise: int = total - meaningful
        video_ids: set = {str(c['video_id']) for c in group if c.get('video_id')}

        result.append({
            'tier': tier,
            'label': TIER_LABELS.get(tier, tier.title()),
            'video_count': len(video_ids),
            'total_count': total,
            'comment_count': len(top_level),
            'reply_count': len(replies),
            'meaningful_count': meaningful,
            'meaningful_pct': _pct(meaningful, total),
            'noise_count': noise,
            'noise_pct': _pct(noise, total),
            'sentiment_summary': _sentiment_counts(group),
            'top_keywords_by_sentiment': _top_keywords_by_sentiment_local(
                group, TOP_KEYWORDS_PER_TIER_SENTIMENT
            ),
            'top_words': _top_words(group, TOP_WORDS_PER_TIER),
            'top_themes': _top_themes(group, TOP_THEMES_PER_TIER)
        })

    return result


def _overall_summary(
    comments: List[Dict[str, Any]],
    account_type_map: Dict[str, str]
) -> Dict[str, Any]:
    """Top-of-report numbers: per-tier video/comment counts, comment vs. reply."""
    tiers: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for comment in comments:
        raw_type: str = _account_type_of(comment, account_type_map)
        tiers[classify_tier(raw_type)].append(comment)

    by_tier: List[Dict[str, Any]] = []
    for tier in TIER_ORDER:
        group: List[Dict[str, Any]] = tiers.get(tier) or []
        if not group:
            continue

        video_ids: set = {str(c['video_id']) for c in group if c.get('video_id')}
        by_tier.append({
            'tier': tier,
            'label': TIER_LABELS.get(tier, tier.title()),
            'video_count': len(video_ids),
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
    account_type_map: Optional[Dict[str, str]] = None
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

    env = Environment(
        loader=FileSystemLoader(template_dir),
        autoescape=select_autoescape(['html', 'j2'])
    )
    template = env.get_template(template_name)

    return template.render(
        generated_at=meta['generated_at'],
        source_file=meta['source_file'],
        date_from=meta['date_range']['from'],
        date_to=meta['date_range']['to'],
        total_videos=total_videos,
        total_comments_analyzed=total_analyzed,
        total_comments_excluded_internal=meta['total_comments_excluded_internal'],
        sentiment_summary=data['sentiment_summary'],
        sentiment_method_breakdown=breakdown,
        llm_escalation_pct=llm_escalation_pct,
        top_keywords_overall=data['top_keywords_overall'],
        top_keywords_by_sentiment=data['top_keywords_by_sentiment'],
        sample_quotes=_sample_quotes(comments),
        excluded_accounts_detected=data.get('excluded_accounts_detected', []),
        overall_summary=_overall_summary(comments, account_type_map),
        tier_breakdown=_tier_breakdown(comments, account_type_map)
    )
