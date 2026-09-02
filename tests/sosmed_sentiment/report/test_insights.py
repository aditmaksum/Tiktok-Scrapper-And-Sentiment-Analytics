import math
import random

import pytest

from sosmed_sentiment.report import insights


def _comment(label, likes=0, month='2026-01', day='05', tokens=None, method='model'):
    return {
        'sentiment_label': label,
        'digg_count': likes,
        'create_time': '%s-%sT10:00:00' % (month, day),
        'tokens_stemmed': tokens or [],
        'sentiment_method': method,
        'text_raw': 'komentar contoh',
        'username': 'user'
    }


def test_net_score_sign_positive_and_negative():
    # 3 positif, 1 negatif, 1 netral -> base 5, net = 100*(3-1)/5 = 40.0
    assert insights.net_score(3, 1, 5) == 40.0
    # 1 positif, 3 negatif, 1 netral -> base 5, net = 100*(1-3)/5 = -40.0
    assert insights.net_score(1, 3, 5) == -40.0


def test_net_score_zero_base_does_not_raise():
    assert insights.net_score(0, 0, 0) == 0.0


def test_classified_base_excludes_unclassified():
    counts = {'positif': 10, 'negatif': 5, 'netral': 3, 'tidak_terklasifikasi': 20}
    # 10 + 5 + 3, the 20 unclassified never enter the base.
    assert insights.classified_base(counts) == 18


def test_build_metrics_on_empty_comments_does_not_raise():
    metrics = insights.build_metrics({'comments': []})

    assert metrics['total_comments'] == 0
    assert metrics['classified_total'] == 0
    assert metrics['net_overall'] == 0.0
    assert metrics['trend'] == []
    assert metrics['explorer_rows'] == []


def test_build_metrics_all_unclassified_has_zero_base_no_division_error():
    comments = [_comment('tidak_terklasifikasi') for _ in range(5)]
    metrics = insights.build_metrics({'comments': comments})

    assert metrics['classified_total'] == 0
    assert metrics['net_overall'] == 0.0
    assert metrics['data_quality']['unclassified_count'] == 5


def test_negation_word_survives_into_distinctive_keywords():
    """Regression for Rules.md Sec 2 / plan E-1.

    A fixture where "tidak ngefek" is the distinctive phrase for negatif
    comments. If insights.py ever hand-wrote its own stopword list (like the
    reference script's STOP set, which stripped 'tidak'), 'tidak' would
    silently vanish from the ranking. It must not: filtering.py's
    NEGATION_WORDS is subtracted from the stopword list, never added to it.
    """
    negatif_comments = [
        _comment('negatif', tokens=['tidak', 'ngefek', 'produk'])
        for _ in range(insights.MIN_KEYWORD_DOC_COUNT + 5)
    ]
    # A large, differently-worded positif/netral pool so 'tidak' is
    # distinctively negatif rather than evenly spread across labels.
    other_comments = [
        _comment('positif', tokens=['bagus', 'mantap', 'suka'])
        for _ in range(insights.MIN_KEYWORD_DOC_COUNT + 5)
    ] + [
        _comment('netral', tokens=['tanya', 'dosis', 'umur'])
        for _ in range(insights.MIN_KEYWORD_DOC_COUNT + 5)
    ]

    metrics = insights.build_metrics({'comments': negatif_comments + other_comments})
    negatif_keywords = {row['keyword'] for row in metrics['keywords_distinctive']['negatif']}

    assert 'tidak' in negatif_keywords
    assert 'ngefek' in negatif_keywords


def test_one_denominator_kpi_and_trend_use_the_same_base():
    """E-2 regression: KPI net and the trend's net must share one denominator.

    All comments fall in a single month with 20%% unclassified. The KPI net
    (net_overall) and that month's trend net must be numerically identical -
    both are net_score() over classified_base(), never sum(all counts).
    """
    comments = (
        [_comment('positif', month='2026-03') for _ in range(8)]
        + [_comment('negatif', month='2026-03') for _ in range(4)]
        + [_comment('netral', month='2026-03') for _ in range(8)]
        + [_comment('tidak_terklasifikasi', month='2026-03') for _ in range(5)]
    )
    # classified base = 8 + 4 + 8 = 20, unclassified = 5 -> 20% of 25 total.
    metrics = insights.build_metrics({'comments': comments})

    assert metrics['classified_total'] == 20
    expected_net = insights.net_score(8, 4, 20)  # (8-4)/20*100 = 20.0
    assert metrics['net_overall'] == expected_net
    assert len(metrics['trend']) == 1
    assert metrics['trend'][0]['net'] == expected_net
    assert metrics['trend'][0]['total'] == 25  # volume floor counts unclassified too


def test_monthly_trend_is_not_pooled_and_shows_a_reversal():
    """UC-6 regression: three months, one a reversal, must stay three numbers.

    Month 1 and 2 are strongly positive, month 3 reverses to negative. A
    pooled 3-month figure would average these into a misleadingly positive
    headline; this asserts every month's net is computed and kept separately.
    """
    def month_block(month, pos, neg, neu):
        return (
            [_comment('positif', month=month, day='10') for _ in range(pos)]
            + [_comment('negatif', month=month, day='11') for _ in range(neg)]
            + [_comment('netral', month=month, day='12') for _ in range(neu)]
        )

    comments = (
        month_block('2026-01', pos=18, neg=1, neu=1)   # base 20, net = 100*17/20 = 85.0
        + month_block('2026-02', pos=17, neg=2, neu=1)  # base 20, net = 100*15/20 = 75.0
        + month_block('2026-03', pos=2, neg=17, neu=1)  # base 20, net = 100*-15/20 = -75.0
    )
    metrics = insights.build_metrics({'comments': comments})
    trend = metrics['trend']

    assert [row['month'] for row in trend] == ['2026-01', '2026-02', '2026-03']
    assert trend[0]['net'] == 85.0
    assert trend[1]['net'] == 75.0
    assert trend[2]['net'] == -75.0
    # The three values are genuinely distinct - no blended figure hides the
    # reversal between month 2 and month 3.
    assert len({row['net'] for row in trend}) == 3


def test_build_narrative_trend_finding_lands_in_risk_not_headline():
    """FT-2 / TD-5 regression: the month-over-month trend finding must be
    demoted out of `narrative.headline` into `narrative.risk` - all three
    fix-pass review voices converged on this independently. A caveat
    appended to an already-bolded headline title undercuts itself; the
    demoted note belongs where a reader actually checks for caveats.
    """
    comments = (
        [_comment('positif', month='2026-01', day='10') for _ in range(18)]
        + [_comment('negatif', month='2026-01', day='11') for _ in range(1)]
        + [_comment('netral', month='2026-01', day='12') for _ in range(1)]
        + [_comment('positif', month='2026-02', day='10') for _ in range(2)]
        + [_comment('negatif', month='2026-02', day='11') for _ in range(17)]
        + [_comment('netral', month='2026-02', day='12') for _ in range(1)]
    )
    metrics = insights.build_metrics({'comments': comments})
    assert metrics['trend_last_delta'] is not None

    narrative = metrics['narrative']
    headline_titles = ' '.join(item['title'] for item in narrative['headline'])
    risk_titles = ' '.join(item['title'] for item in narrative['risk'])

    assert 'dibanding' not in headline_titles
    assert 'dibanding' in risk_titles
    assert 'belum diverifikasi terhadap populasi penuh' in risk_titles


def test_build_narrative_trend_caveat_handles_missing_population_gracefully():
    """FT-2: without --total-population-videos, the caveat must drop the
    ratio cleanly - never print a nonsensical "dari None video"."""
    comments = (
        [_comment('positif', month='2026-01', day='10') for _ in range(18)]
        + [_comment('negatif', month='2026-01', day='11') for _ in range(1)]
        + [_comment('netral', month='2026-01', day='12') for _ in range(1)]
        + [_comment('positif', month='2026-02', day='10') for _ in range(2)]
        + [_comment('negatif', month='2026-02', day='11') for _ in range(17)]
        + [_comment('netral', month='2026-02', day='12') for _ in range(1)]
    )
    metrics = insights.build_metrics({'comments': comments}, total_population_videos=None)
    risk_bodies = ' '.join(item['body'] for item in metrics['narrative']['risk'])

    assert 'None' not in risk_bodies


def test_thin_months_are_dropped_by_the_volume_floor():
    comments = [_comment('positif', month='2026-04') for _ in range(insights.MIN_MONTH_VOLUME - 1)]
    metrics = insights.build_metrics({'comments': comments})

    assert metrics['trend'] == []


def test_explorer_rows_are_hard_capped():
    comments = [_comment('netral', likes=i, month='2026-05') for i in range(400)]
    metrics = insights.build_metrics({'comments': comments})

    assert len(metrics['explorer_rows']) == insights.EXPLORER_ROW_CAP


def test_explorer_rows_include_all_four_labels_when_available():
    """Fix #3 regression: the explorer must not be constructible as 100%
    negatif/unclassified when positif/netral comments exist in the corpus.
    """
    comments = (
        [_comment('negatif', month='2026-05') for _ in range(1027)]
        + [_comment('tidak_terklasifikasi', month='2026-05') for _ in range(251)]
        + [_comment('positif', month='2026-05') for _ in range(500)]
        + [_comment('netral', month='2026-05') for _ in range(500)]
    )
    metrics = insights.build_metrics({'comments': comments})
    labels = {row['sentiment_label'] for row in metrics['explorer_rows']}

    assert labels == {'positif', 'negatif', 'netral', 'tidak_terklasifikasi'}
    assert len(metrics['explorer_rows']) == insights.EXPLORER_ROW_CAP


def test_explorer_rows_quota_handles_a_zero_count_label():
    """A label with zero available comments (e.g. no netral) must not crash
    and must not reserve dead slots that starve the cap."""
    comments = (
        [_comment('negatif', month='2026-05') for _ in range(80)]
        + [_comment('tidak_terklasifikasi', month='2026-05') for _ in range(80)]
        + [_comment('positif', month='2026-05') for _ in range(80)]
    )
    metrics = insights.build_metrics({'comments': comments})
    labels = {row['sentiment_label'] for row in metrics['explorer_rows']}

    assert 'netral' not in labels
    assert labels == {'positif', 'negatif', 'tidak_terklasifikasi'}
    assert len(metrics['explorer_rows']) == insights.EXPLORER_ROW_CAP


def test_explorer_sampling_uses_a_local_rng_not_the_global_seed():
    """E-5 regression: must never call random.seed() at module or call scope."""
    before = random.getstate()
    comments = [_comment('netral', month='2026-05', likes=i) for i in range(500)]

    insights.build_metrics({'comments': comments})

    assert random.getstate() == before


def test_explorer_sampling_is_deterministic_across_calls():
    comments = [_comment('netral', month='2026-05', likes=i) for i in range(500)]

    first = insights.build_metrics({'comments': list(comments)})['explorer_rows']
    second = insights.build_metrics({'comments': list(comments)})['explorer_rows']

    assert first == second


def test_video_leaderboard_applies_the_minimum_comment_floor():
    per_video = [
        {
            'video_id': 'thin', 'caption': 'thin video',
            'sentiment_summary': {'positif': 5, 'negatif': 0, 'netral': 0},
            'total_comments_analyzed': 5
        },
        {
            'video_id': 'thick', 'caption': 'thick video',
            'sentiment_summary': {
                'positif': insights.MIN_VIDEO_COMMENTS, 'negatif': 0, 'netral': 0
            },
            'total_comments_analyzed': insights.MIN_VIDEO_COMMENTS
        }
    ]
    metrics = insights.build_metrics({'comments': [], 'per_video': per_video})

    assert metrics['video_leaderboard']['total_count'] == 2
    assert metrics['video_leaderboard']['eligible_count'] == 1
    eligible_ids = {v['video_id'] for v in metrics['video_leaderboard']['best']}
    assert eligible_ids == {'thick'}
    # loudest is not floor-gated - the thin video should still be visible there.
    loudest_ids = {v['video_id'] for v in metrics['video_leaderboard']['loudest']}
    assert 'thin' in loudest_ids


def _tokened_comment(label, tokens, likes=0, comment_id=None, username='user', video_id=None):
    return {
        'comment_id': comment_id,
        'sentiment_label': label,
        'digg_count': likes,
        'tokens_stemmed': tokens,
        'text_raw': 'komentar contoh',
        'username': username,
        'video_id': video_id,
        'create_time': '2026-01-05T10:00:00'
    }


# --- T-ENG-1: _weighted_log_odds() -------------------------------------

def test_weighted_log_odds_returns_empty_for_empty_target():
    rows = insights._weighted_log_odds([], [_tokened_comment('positif', ['bagus'])])
    assert rows == []


def test_weighted_log_odds_handles_empty_comparison_without_dividing_by_zero():
    target = [_tokened_comment('positif', ['bagus']) for _ in range(insights.MIN_KEYWORD_DOC_COUNT)]
    rows = insights._weighted_log_odds(target, [])
    # comparison is empty so c_other/n_other are both 0 - must not raise.
    assert isinstance(rows, list)


def test_weighted_log_odds_identical_target_and_comparison_does_not_crash():
    """Symmetric case (target is comparison in full): every count is fully
    "self", c_other collapses to 0 rather than going negative or raising -
    the function must still return a well-formed, finite ranking."""
    pool = [_tokened_comment('positif', ['bagus']) for _ in range(insights.MIN_KEYWORD_DOC_COUNT + 5)]
    rows = insights._weighted_log_odds(pool, pool)

    assert rows
    for row in rows:
        assert math.isfinite(row['score'])


def test_weighted_log_odds_filters_below_the_min_doc_count_floor():
    target = [
        _tokened_comment('positif', ['bagus']) for _ in range(insights.MIN_KEYWORD_DOC_COUNT - 1)
    ]
    comparison = target + [_tokened_comment('negatif', ['jelek']) for _ in range(50)]
    rows = insights._weighted_log_odds(target, comparison)

    assert not any(row['keyword'] == 'bagus' for row in rows)


# --- T-ENG-2: _distinctive_keywords_by_tier() ---------------------------

def test_distinctive_keywords_by_tier_handles_a_zero_comment_tier():
    comments_by_tier = {
        'kol': [_tokened_comment('positif', ['bagus']) for _ in range(insights.MIN_KEYWORD_DOC_COUNT + 2)],
        'official': [],
        'affiliate': [],
        'unknown': []
    }
    result = insights._distinctive_keywords_by_tier(comments_by_tier)

    assert result['official'] == []
    assert result['unknown'] == []


def test_distinctive_keywords_by_tier_tier_below_doc_count_floor_is_empty():
    comments_by_tier = {
        'kol': [_tokened_comment('positif', ['bagus']) for _ in range(insights.MIN_KEYWORD_DOC_COUNT - 1)],
        'official': [_tokened_comment('netral', ['harga']) for _ in range(50)]
    }
    result = insights._distinctive_keywords_by_tier(comments_by_tier)

    assert result['kol'] == []


def test_distinctive_keywords_by_tier_compares_against_full_corpus_not_tier_excluded():
    """D4: the comparison pool for one tier's distinctive words is every
    tier's comments, target tier included - not the other tiers only. A word
    used identically often in every tier should score near zero, not show up
    as falsely distinctive because the target's own usage was excluded from
    the comparison denominator.
    """
    shared_tokens = ['umur']
    comments_by_tier = {
        'kol': [_tokened_comment('netral', shared_tokens) for _ in range(40)],
        'official': [_tokened_comment('netral', shared_tokens) for _ in range(40)]
    }
    result = insights._distinctive_keywords_by_tier(comments_by_tier)

    for tier_rows in result.values():
        for row in tier_rows:
            if row['keyword'] == 'umur':
                assert row['score'] == pytest.approx(0.0, abs=0.05)


# --- T-ENG-3: _theme_matches() ------------------------------------------

def test_theme_matches_comment_with_no_theme_tokens_matches_nothing():
    themes = insights._theme_matches([_tokened_comment('netral', ['halo', 'semangat'])])
    assert all(row['count'] == 0 for row in themes.values())


def test_theme_matches_one_comment_can_match_multiple_themes():
    """D7: themes are independent counts, not mutually exclusive."""
    tokens = ['minum', 'harga', 'umur', 'efek', 'hasil', 'asli']
    themes = insights._theme_matches([_tokened_comment('netral', tokens)])

    assert all(row['count'] == 1 for row in themes.values())


def test_theme_matches_is_safe_against_a_token_containing_regex_metacharacters():
    """D12: THEME_PATTERNS matches theme vocabulary against the joined
    tokens_stemmed string - the token content is search TARGET, never
    compiled into a pattern, so a token full of regex metacharacters must
    not raise and must not falsely match a theme whose vocabulary isn't
    actually present as a bounded word."""
    tokens = ['a.*b', '$(evil)^', 'harga']
    themes = insights._theme_matches([_tokened_comment('netral', tokens)])

    assert themes['price_availability']['count'] == 1
    assert themes['dosage_usage']['count'] == 0
    assert themes['safety_side_effects']['count'] == 0


def test_theme_matches_respects_word_boundaries():
    """A stemmed token that merely contains 'asli' as a substring (not the
    whole token) must not match counterfeit_authenticity."""
    themes = insights._theme_matches([_tokened_comment('netral', ['originalitas'])])
    assert themes['counterfeit_authenticity']['count'] == 0

    themes_exact = insights._theme_matches([_tokened_comment('netral', ['asli'])])
    assert themes_exact['counterfeit_authenticity']['count'] == 1


def test_theme_matches_sorted_by_frequency_descending():
    tokens_per_comment = [['minum'], ['minum'], ['harga']]
    comments = [_tokened_comment('netral', tokens) for tokens in tokens_per_comment]
    themes = insights._theme_matches(comments)

    counts = [row['count'] for row in themes.values()]
    assert counts == sorted(counts, reverse=True)


# --- T-ENG-4: _tier_example_comments() -----------------------------------

def test_tier_example_comments_returns_all_without_padding_when_fewer_than_limit():
    comments = [_tokened_comment('positif', ['bagus'], likes=i) for i in range(2)]
    examples = insights._tier_example_comments(comments)

    assert len(examples) == 2


def test_tier_example_comments_empty_tier_returns_empty_list():
    assert insights._tier_example_comments([]) == []


def test_tier_example_comments_ties_on_digg_count_break_deterministically():
    comments = [
        _tokened_comment('positif', ['bagus'], likes=10, comment_id='b', username='userb'),
        _tokened_comment('positif', ['mantap'], likes=10, comment_id='a', username='usera')
    ]
    first = insights._tier_example_comments(comments)
    second = insights._tier_example_comments(list(reversed(comments)))

    assert first == second


# --- T-ENG-6/D8: _tier_breakdown()-analog regression via build_tier_deep_dive --

def test_build_tier_deep_dive_always_returns_all_four_tiers():
    """CRITICAL regression: a tier with zero comments must still appear as a
    zero-value row, never be omitted - matches html_builder._tier_breakdown()'s
    same fix (T-ENG-6)."""
    comments_by_tier = {
        'kol': [_tokened_comment('positif', ['bagus'], video_id='v1') for _ in range(5)]
    }
    rows = insights._build_tier_deep_dive(comments_by_tier)
    tiers_present = {row['tier'] for row in rows}

    assert tiers_present == {'kol', 'official', 'affiliate', 'unknown'}
    unknown_row = next(row for row in rows if row['tier'] == 'unknown')
    assert unknown_row['comment_count'] == 0
    assert unknown_row['video_count'] == 0
    assert unknown_row['label'] == 'Tidak diketahui'


def test_build_tier_deep_dive_orders_by_comment_volume_descending():
    comments_by_tier = {
        'kol': [_tokened_comment('positif', ['bagus']) for _ in range(3)],
        'official': [_tokened_comment('positif', ['bagus']) for _ in range(10)],
        'affiliate': [_tokened_comment('positif', ['bagus']) for _ in range(1)]
    }
    rows = insights._build_tier_deep_dive(comments_by_tier)

    assert [row['tier'] for row in rows] == ['official', 'kol', 'affiliate', 'unknown']


def test_build_tier_deep_dive_accepts_a_video_counts_override():
    comments_by_tier = {'kol': [_tokened_comment('positif', ['bagus'], video_id='v1')]}
    rows = insights._build_tier_deep_dive(comments_by_tier, video_counts={'kol': 61})
    kol_row = next(row for row in rows if row['tier'] == 'kol')

    assert kol_row['video_count'] == 61


# --- T-ENG-5: _build_tier_narrative() -------------------------------------

def test_build_tier_narrative_degenerate_single_tier_case():
    """The tier with data is the only one - nothing to compare against."""
    tier = {'label': 'KOL', 'comment_count': 10, 'video_count': 2}
    sentences = insights._build_tier_narrative(tier, [])

    assert len(sentences) == 1
    assert 'satu-satunya' in sentences[0]['title']


def test_build_tier_narrative_comparison_direction_matches_known_delta():
    """A known cross-tier delta must produce the correct comparison
    direction, not merely be present (fix pass 2026-09-02c test gap)."""
    tier = {
        'label': 'KOL', 'net': 50.0, 'comment_count': 100, 'video_count': 10,
        'pct_of_total': 60.0, 'themes': []
    }
    others = [
        {'label': 'Official', 'net': 10.0, 'comment_count': 50, 'video_count': 5}
    ]
    sentences = insights._build_tier_narrative(tier, others)

    assert 'lebih tinggi' in sentences[0]['body']
    assert '+50.0' in sentences[0]['title']


def test_engagement_top10_share_and_trimmed_net():
    # One comment with 1000 likes (negatif) dominates; the rest are small and positif.
    comments = [_comment('negatif', likes=1000, month='2026-06')]
    comments += [_comment('positif', likes=1, month='2026-06') for _ in range(20)]

    metrics = insights.build_metrics({'comments': comments})
    engagement = metrics['engagement']

    assert engagement['total_likes'] == 1000 + 20
    # "top 10" is ten comments, not the single loudest one: the dominating
    # 1000-like comment plus the next nine 1-like comments = 1009 of 1020.
    assert engagement['top10_like_share_pct'] == pytest.approx(
        insights._pct(1009, 1020), abs=0.01
    )
    # once the single dominating comment is trimmed off, the remaining 20
    # positif-only comments must swing the trimmed net fully positive.
    assert engagement['net_by_likes_trimmed'] == 100.0
