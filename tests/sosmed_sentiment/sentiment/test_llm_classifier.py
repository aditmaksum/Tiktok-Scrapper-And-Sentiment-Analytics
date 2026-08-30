import json

from unittest.mock import MagicMock, patch

import pytest

from sosmed_sentiment.errors import LLMCallError
from sosmed_sentiment.sentiment.llm_classifier import classify_via_llm


def fake_response(content):
    message = MagicMock()
    message.content = content
    choice = MagicMock()
    choice.message = message
    response = MagicMock()
    response.choices = [choice]
    return response


@patch('sosmed_sentiment.sentiment.llm_classifier.OpenAI')
def test_a_successful_call_returns_the_parsed_label(mock_openai_cls):
    client = MagicMock()
    client.chat.completions.create.return_value = fake_response(
        json.dumps({'label': 'positif', 'confidence': 0.9})
    )
    mock_openai_cls.return_value = client

    result = classify_via_llm('bagus banget', model='gpt-test')

    assert result == {
        'sentiment_label': 'positif', 'sentiment_confidence': 0.9,
        'sentiment_method': 'llm'
    }


@patch('sosmed_sentiment.sentiment.llm_classifier.time.sleep')
@patch('sosmed_sentiment.sentiment.llm_classifier.OpenAI')
def test_transient_failures_are_retried_before_succeeding(mock_openai_cls, mock_sleep):
    client = MagicMock()
    client.chat.completions.create.side_effect = [
        Exception('timeout'),
        fake_response(json.dumps({'label': 'negatif', 'confidence': 0.7}))
    ]
    mock_openai_cls.return_value = client

    result = classify_via_llm('jelek', model='gpt-test')

    assert result['sentiment_label'] == 'negatif'
    assert client.chat.completions.create.call_count == 2


@patch('sosmed_sentiment.sentiment.llm_classifier.time.sleep')
@patch('sosmed_sentiment.sentiment.llm_classifier.OpenAI')
def test_persistent_failure_raises_llm_call_error_after_max_retries(mock_openai_cls, mock_sleep):
    client = MagicMock()
    client.chat.completions.create.side_effect = Exception('down')
    mock_openai_cls.return_value = client

    with pytest.raises(LLMCallError):
        classify_via_llm('apapun', model='gpt-test')

    assert client.chat.completions.create.call_count == 3  # 1 + MAX_RETRIES(2)


@patch('sosmed_sentiment.sentiment.llm_classifier.OpenAI')
def test_an_unexpected_label_from_the_model_is_treated_as_a_failure(mock_openai_cls):
    client = MagicMock()
    client.chat.completions.create.return_value = fake_response(
        json.dumps({'label': 'sangat_positif', 'confidence': 0.9})
    )
    mock_openai_cls.return_value = client

    with pytest.raises(LLMCallError):
        classify_via_llm('bagus', model='gpt-test')
