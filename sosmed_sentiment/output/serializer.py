from collections import Counter, defaultdict
from datetime import datetime
from typing import Any, Dict, List

SENTIMENT_LABELS: tuple = ('positif', 'negatif', 'netral', 'tidak_terklasifikasi')

# autoplan Eng HIGH #2 (2026-08-30): this used to hardcode {'lexicon': ...} only,
# so a run using any other sentiment_method silently reported 0 for it. Known
# methods are zero-filled so the report template's .get() calls stay reliable,
# then whatever the run actually produced is merged on top - an unrecognized
# future method name still surfaces instead of vanishing.
KNOWN_SENTIMENT_METHODS: tuple = ('model', 'model_failed', 'llm', 'llm_failed', 'lexicon')


def _pct(
    count: int,
    total: int
) -> float:
    return round(100.0 * count / total, 2) if total else 0.0


def _sentiment_summary(
    comments: List[Dict[str, Any]]
) -> Dict[str, Any]:
    counts: Counter = Counter(comment['sentiment_label'] for comment in comments)
    total: int = len(comments)

    summary: Dict[str, Any] = {label: counts.get(label, 0) for label in SENTIMENT_LABELS}
    summary['positif_pct'] = _pct(counts.get('positif', 0), total)
    summary['negatif_pct'] = _pct(counts.get('negatif', 0), total)
    summary['netral_pct'] = _pct(counts.get('netral', 0), total)

    return summary


def _per_video(
    comments: List[Dict[str, Any]],
    top_keywords_by_video: Dict[str, List[Dict[str, Any]]]
) -> List[Dict[str, Any]]:
    by_video: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for comment in comments:
        by_video[comment['video_id']].append(comment)

    result: List[Dict[str, Any]] = []
    for video_id, video_comments in by_video.items():
        counts: Counter = Counter(c['sentiment_label'] for c in video_comments)
        result.append({
            'video_id': video_id,
            'caption': video_comments[0]['video_caption'],
            'total_comments_analyzed': len(video_comments),
            'sentiment_summary': {
                'positif': counts.get('positif', 0),
                'negatif': counts.get('negatif', 0),
                'netral': counts.get('netral', 0)
            },
            'top_keywords': [
                {'keyword': item['keyword'], 'count': item['count']}
                for item in top_keywords_by_video.get(video_id, [])
            ]
        })

    return result


def build_analysis_result(
    run_id: str,
    source_file: str,
    total_comments_raw: int,
    comments: List[Dict[str, Any]],
    top_keywords_overall: List[Dict[str, Any]],
    top_keywords_by_sentiment: Dict[str, List[Dict[str, Any]]],
    config_used: Dict[str, Any],
    top_keywords_by_video: Dict[str, List[Dict[str, Any]]] = None,
    excluded_accounts_detected: List[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """Assemble analysis_result.json exactly per Schema.md §4.

    comments here are the ANALYZED set (excluded ones already removed by the
    caller, but total_comments_raw is the pre-exclude count so meta stays
    honest about how much was thrown away).
    """
    excluded_internal: int = total_comments_raw - len(comments)
    method_counts: Counter = Counter(c['sentiment_method'] for c in comments)

    dates: List[str] = [c['create_time'] for c in comments if c.get('create_time')]

    return {
        'meta': {
            'run_id': run_id,
            'generated_at': datetime.now().strftime('%Y-%m-%dT%H:%M:%S'),
            'source_file': source_file,
            'date_range': {
                'from': min(dates) if dates else '',
                'to': max(dates) if dates else ''
            },
            'total_videos': len({c['video_id'] for c in comments}),
            'total_comments_raw': total_comments_raw,
            'total_comments_excluded_internal': excluded_internal,
            'total_comments_analyzed': len(comments),
            'sentiment_method_breakdown': {
                **{method: 0 for method in KNOWN_SENTIMENT_METHODS},
                **method_counts
            },
            'config_used': config_used
        },
        'sentiment_summary': _sentiment_summary(comments),
        'top_keywords_overall': top_keywords_overall,
        'top_keywords_by_sentiment': top_keywords_by_sentiment,
        'per_video': _per_video(comments, top_keywords_by_video or {}),
        'comments': [
            {
                'comment_id': c['comment_id'],
                'video_id': c['video_id'],
                'is_reply': c['is_reply'],
                'parent_comment_id': c['parent_comment_id'],
                'username': c['username'],
                'text_raw': c['text_raw'],
                'text_clean': c.get('text_clean', ''),
                'tokens_stemmed': c.get('tokens_stemmed', []),
                'emoji_found': c.get('emoji_found', []),
                'sentiment_label': c['sentiment_label'],
                'sentiment_confidence': c['sentiment_confidence'],
                'sentiment_method': c['sentiment_method'],
                'create_time': c['create_time'],
                'digg_count': c.get('digg_count', 0)
            }
            for c in comments
        ],
        'excluded_accounts_detected': excluded_accounts_detected or []
    }
