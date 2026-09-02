from unittest.mock import patch

from sosmed_sentiment.errors import LLMCallError, ModelClassifyError
from sosmed_sentiment.sentiment.hybrid import (
    classify_comment, is_ambiguous, llm_failure_ratio_exceeds_threshold
)


def test_a_confident_result_is_not_ambiguous():
    assert is_ambiguous(confidence=0.9, threshold=0.6) is False


def test_a_low_confidence_result_is_ambiguous():
    assert is_ambiguous(confidence=0.4, threshold=0.6) is True


def test_confidence_exactly_at_threshold_is_not_ambiguous():
    assert is_ambiguous(confidence=0.6, threshold=0.6) is False


@patch('sosmed_sentiment.sentiment.hybrid.classify_via_llm')
@patch('sosmed_sentiment.sentiment.hybrid.model_classify')
def test_a_confident_model_result_never_calls_the_llm(mock_model, mock_llm):
    mock_model.return_value = {
        'sentiment_label': 'positif', 'sentiment_confidence': 0.9, 'sentiment_method': 'model'
    }

    result = classify_comment('bagus banget', llm_model='gpt-test', threshold_confidence=0.6)

    assert result['sentiment_method'] == 'model'
    mock_llm.assert_not_called()


@patch('sosmed_sentiment.sentiment.hybrid.classify_via_llm')
@patch('sosmed_sentiment.sentiment.hybrid.model_classify')
def test_a_low_confidence_model_result_escalates_to_the_llm(mock_model, mock_llm):
    mock_model.return_value = {
        'sentiment_label': 'netral', 'sentiment_confidence': 0.3, 'sentiment_method': 'model'
    }
    mock_llm.return_value = {
        'sentiment_label': 'positif', 'sentiment_confidence': 0.7, 'sentiment_method': 'llm'
    }

    result = classify_comment('entahlah gimana', llm_model='gpt-test', threshold_confidence=0.6)

    assert result['sentiment_method'] == 'llm'
    mock_llm.assert_called_once()


@patch('sosmed_sentiment.sentiment.hybrid.classify_via_llm')
@patch('sosmed_sentiment.sentiment.hybrid.model_classify')
def test_a_model_classify_failure_escalates_to_the_llm_instead_of_aborting(mock_model, mock_llm):
    mock_model.side_effect = ModelClassifyError('boom')
    mock_llm.return_value = {
        'sentiment_label': 'negatif', 'sentiment_confidence': 0.8, 'sentiment_method': 'llm'
    }

    result = classify_comment('komentar aneh', llm_model='gpt-test', threshold_confidence=0.6)

    assert result['sentiment_method'] == 'llm'
    mock_llm.assert_called_once()


@patch('sosmed_sentiment.sentiment.hybrid.classify_via_llm')
@patch('sosmed_sentiment.sentiment.hybrid.model_classify')
def test_a_failed_llm_call_becomes_tidak_terklasifikasi(mock_model, mock_llm):
    mock_model.return_value = {
        'sentiment_label': 'netral', 'sentiment_confidence': 0.3, 'sentiment_method': 'model'
    }
    mock_llm.side_effect = LLMCallError('down')

    result = classify_comment('entahlah gimana', llm_model='gpt-test', threshold_confidence=0.6)

    assert result['sentiment_label'] == 'tidak_terklasifikasi'
    assert result['sentiment_method'] == 'llm_failed'


def test_failure_ratio_ignores_non_escalated_comments():
    comments = [{'sentiment_method': 'model'}] * 100

    assert llm_failure_ratio_exceeds_threshold(comments) is False


def test_failure_ratio_is_relative_to_escalated_comments_only():
    comments = (
        [{'sentiment_method': 'model'}] * 90
        + [{'sentiment_method': 'llm'}] * 8
        + [{'sentiment_method': 'llm_failed'}] * 2
    )

    # 2/10 escalated = 20%, above the 10% threshold - even though it's
    # only 2% of the whole batch.
    assert llm_failure_ratio_exceeds_threshold(comments) is True


def test_failure_ratio_under_threshold_does_not_trip():
    comments = [{'sentiment_method': 'llm'}] * 19 + [{'sentiment_method': 'llm_failed'}] * 1

    assert llm_failure_ratio_exceeds_threshold(comments) is False
