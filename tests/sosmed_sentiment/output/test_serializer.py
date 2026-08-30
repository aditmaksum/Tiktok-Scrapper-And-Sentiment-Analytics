from sosmed_sentiment.output.serializer import build_analysis_result


def comment(comment_id, video_id, label, method='lexicon', **extra):
    data = {
        'comment_id': comment_id, 'video_id': video_id, 'is_reply': False,
        'parent_comment_id': None, 'username': 'u%s' % comment_id,
        'text_raw': 'raw', 'video_caption': 'caption %s' % video_id,
        'sentiment_label': label, 'sentiment_confidence': 0.8,
        'sentiment_method': method, 'create_time': '2026-08-30T00:00:00',
        'digg_count': 0
    }
    data.update(extra)
    return data


def test_sentiment_summary_counts_and_percentages():
    comments = [
        comment('1', 'v1', 'positif'),
        comment('2', 'v1', 'positif'),
        comment('3', 'v1', 'negatif'),
        comment('4', 'v1', 'netral')
    ]

    result = build_analysis_result(
        run_id='r1', source_file='comments.json', total_comments_raw=4,
        comments=comments, top_keywords_overall=[], top_keywords_by_sentiment={},
        config_used={}
    )

    assert result['sentiment_summary']['positif'] == 2
    assert result['sentiment_summary']['positif_pct'] == 50.0
    assert result['sentiment_summary']['tidak_terklasifikasi'] == 0


def test_excluded_count_is_raw_minus_analyzed():
    comments = [comment('1', 'v1', 'positif')]

    result = build_analysis_result(
        run_id='r1', source_file='comments.json', total_comments_raw=5,
        comments=comments, top_keywords_overall=[], top_keywords_by_sentiment={},
        config_used={}
    )

    assert result['meta']['total_comments_raw'] == 5
    assert result['meta']['total_comments_analyzed'] == 1
    assert result['meta']['total_comments_excluded_internal'] == 4


def test_method_breakdown_counts_each_method():
    comments = [
        comment('1', 'v1', 'positif', method='lexicon'),
        comment('2', 'v1', 'negatif', method='llm'),
        comment('3', 'v1', 'tidak_terklasifikasi', method='llm_failed')
    ]

    result = build_analysis_result(
        run_id='r1', source_file='comments.json', total_comments_raw=3,
        comments=comments, top_keywords_overall=[], top_keywords_by_sentiment={},
        config_used={}
    )

    assert result['meta']['sentiment_method_breakdown'] == {
        'lexicon': 1, 'llm': 1, 'llm_failed': 1
    }


def test_per_video_groups_correctly():
    comments = [
        comment('1', 'v1', 'positif'),
        comment('2', 'v1', 'negatif'),
        comment('3', 'v2', 'positif')
    ]

    result = build_analysis_result(
        run_id='r1', source_file='comments.json', total_comments_raw=3,
        comments=comments, top_keywords_overall=[], top_keywords_by_sentiment={},
        config_used={}
    )

    by_id = {video['video_id']: video for video in result['per_video']}
    assert by_id['v1']['total_comments_analyzed'] == 2
    assert by_id['v2']['total_comments_analyzed'] == 1


def test_zero_comments_does_not_crash():
    result = build_analysis_result(
        run_id='r1', source_file='comments.json', total_comments_raw=0,
        comments=[], top_keywords_overall=[], top_keywords_by_sentiment={},
        config_used={}
    )

    assert result['sentiment_summary']['positif'] == 0
    assert result['meta']['date_range'] == {'from': '', 'to': ''}
    assert result['comments'] == []


def test_excluded_accounts_detected_defaults_to_empty_list():
    result = build_analysis_result(
        run_id='r1', source_file='comments.json', total_comments_raw=1,
        comments=[comment('1', 'v1', 'positif')], top_keywords_overall=[],
        top_keywords_by_sentiment={}, config_used={}
    )

    assert result['excluded_accounts_detected'] == []


def test_excluded_accounts_detected_is_passed_through():
    detected = [{'username': 'yaylesupport', 'total_muncul': 5, 'alasan': 'internal_account'}]

    result = build_analysis_result(
        run_id='r1', source_file='comments.json', total_comments_raw=1,
        comments=[comment('1', 'v1', 'positif')], top_keywords_overall=[],
        top_keywords_by_sentiment={}, config_used={},
        excluded_accounts_detected=detected
    )

    assert result['excluded_accounts_detected'] == detected


def test_comments_serializes_every_required_schema_field():
    comments = [comment('1', 'v1', 'positif')]

    result = build_analysis_result(
        run_id='r1', source_file='comments.json', total_comments_raw=1,
        comments=comments, top_keywords_overall=[], top_keywords_by_sentiment={},
        config_used={}
    )

    fields = result['comments'][0].keys()
    for required in (
        'comment_id', 'video_id', 'is_reply', 'parent_comment_id', 'username',
        'text_raw', 'text_clean', 'tokens_stemmed', 'emoji_found',
        'sentiment_label', 'sentiment_confidence', 'sentiment_method',
        'create_time', 'digg_count'
    ):
        assert required in fields
