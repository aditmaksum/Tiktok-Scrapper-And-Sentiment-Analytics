import os

from typing import Any, Dict, List

from jinja2 import Environment, FileSystemLoader, select_autoescape

from sosmed_sentiment.errors import ReportBuildError

REQUIRED_TOP_LEVEL_FIELDS: tuple = (
    'meta', 'sentiment_summary', 'top_keywords_overall',
    'top_keywords_by_sentiment', 'comments'
)

TEMPLATE_DIR: str = os.path.join(os.path.dirname(__file__), 'templates')
SAMPLE_QUOTES_PER_LABEL: int = 5


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
    template_name: str = 'report.html.j2'
) -> str:
    """analysis_result.json (already parsed) -> rendered HTML string.

    Raises ReportBuildError on a schema violation - never returns a partial
    or empty-looking HTML for invalid input (PRD.md FR-07 kriteria gagal).

    template_dir/template_name let cli.generate_report's --template flag
    point at an analyst-supplied template without duplicating everything
    else this function does to build the render context.
    """
    _validate(data)

    meta: Dict[str, Any] = data['meta']
    total_analyzed: int = meta['total_comments_analyzed']
    breakdown: Dict[str, int] = meta['sentiment_method_breakdown']
    escalated: int = breakdown.get('llm', 0) + breakdown.get('llm_failed', 0)
    llm_escalation_pct: float = round(100.0 * escalated / total_analyzed, 1) if total_analyzed else 0.0

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
        total_comments_analyzed=total_analyzed,
        total_comments_excluded_internal=meta['total_comments_excluded_internal'],
        sentiment_summary=data['sentiment_summary'],
        sentiment_method_breakdown=breakdown,
        llm_escalation_pct=llm_escalation_pct,
        top_keywords_overall=data['top_keywords_overall'],
        top_keywords_by_sentiment=data['top_keywords_by_sentiment'],
        sample_quotes=_sample_quotes(data['comments']),
        excluded_accounts_detected=data.get('excluded_accounts_detected', [])
    )
