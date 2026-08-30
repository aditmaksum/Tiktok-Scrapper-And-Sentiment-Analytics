from unittest.mock import patch

from sosmed_sentiment.errors import LLMCallError
from sosmed_sentiment.sentiment.hybrid import (
    classify_comment, is_ambiguous, llm_failure_ratio_exceeds_threshold
)

LEXICON = {'bagus': 0.8, 'jelek': -0.8}


def test_a_clear_score_is_not_ambiguous():
    assert is_ambiguous(score=0.8, oov_ratio=0.0) is False


def test_a_score_inside_the_neutral_band_is_ambiguous():
    assert is_ambiguous(score=0.05, oov_ratio=0.0) is True


def test_high_oov_ratio_is_ambiguous_even_with_a_clear_score():
    assert is_ambiguous(score=0.8, oov_ratio=0.6) is True


@patch('sosmed_sentiment.sentiment.hybrid.classify_via_llm')
def test_a_clear_lexicon_score_never_calls_the_llm(mock_llm):
    result = classify_comment(['bagus'], 'bagus', LEXICON, model='gpt-test')

    assert result['sentiment_method'] == 'lexicon'
    mock_llm.assert_not_called()


@patch('sosmed_sentiment.sentiment.hybrid.classify_via_llm')
def test_an_ambiguous_score_escalates_to_the_llm(mock_llm):
    mock_llm.return_value = {
        'sentiment_label': 'positif', 'sentiment_confidence': 0.6, 'sentiment_method': 'llm'
    }

    result = classify_comment(['entahlah'], 'entahlah gimana ya', LEXICON, model='gpt-test')

    assert result['sentiment_method'] == 'llm'
    mock_llm.assert_called_once()


@patch('sosmed_sentiment.sentiment.hybrid.classify_via_llm')
def test_a_failed_llm_call_becomes_tidak_terklasifikasi(mock_llm):
    mock_llm.side_effect = LLMCallError('down')

    result = classify_comment(['entahlah'], 'entahlah gimana ya', LEXICON, model='gpt-test')

    assert result['sentiment_label'] == 'tidak_terklasifikasi'
    assert result['sentiment_method'] == 'llm_failed'


def test_failure_ratio_ignores_lexicon_only_comments():
    comments = [{'sentiment_method': 'lexicon'}] * 100

    assert llm_failure_ratio_exceeds_threshold(comments) is False


def test_failure_ratio_is_relative_to_escalated_comments_only():
    comments = (
        [{'sentiment_method': 'lexicon'}] * 90
        + [{'sentiment_method': 'llm'}] * 8
        + [{'sentiment_method': 'llm_failed'}] * 2
    )

    # 2/10 escalated = 20%, above the 10% threshold - even though it's
    # only 2% of the whole batch.
    assert llm_failure_ratio_exceeds_threshold(comments) is True


def test_failure_ratio_under_threshold_does_not_trip():
    comments = [{'sentiment_method': 'llm'}] * 19 + [{'sentiment_method': 'llm_failed'}] * 1

    assert llm_failure_ratio_exceeds_threshold(comments) is False
