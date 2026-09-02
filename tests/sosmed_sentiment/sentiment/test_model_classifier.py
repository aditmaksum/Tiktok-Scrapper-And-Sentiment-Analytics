from unittest.mock import MagicMock, patch

import pytest

from sosmed_sentiment.errors import ModelClassifyError, ModelLoadError
from sosmed_sentiment.sentiment import model_classifier


@pytest.fixture(autouse=True)
def reset_singleton():
    """Every test starts with no model loaded - the singleton is process-global state."""
    model_classifier._PIPELINE = None
    yield
    model_classifier._PIPELINE = None


def fake_pipeline(return_value):
    pipe = MagicMock()
    pipe.return_value = [return_value]
    return pipe


@patch('sosmed_sentiment.sentiment.model_classifier.pipeline')
def test_load_model_is_called_once_even_across_multiple_loads(mock_pipeline_factory):
    mock_pipeline_factory.return_value = fake_pipeline({'label': 'positive', 'score': 0.9})

    model_classifier.load_model()
    model_classifier.load_model()

    mock_pipeline_factory.assert_called_once()
    assert model_classifier.is_loaded() is True


@patch('sosmed_sentiment.sentiment.model_classifier.pipeline')
def test_load_model_pins_the_revision(mock_pipeline_factory):
    mock_pipeline_factory.return_value = fake_pipeline({'label': 'positive', 'score': 0.9})

    model_classifier.load_model()

    _, kwargs = mock_pipeline_factory.call_args
    assert kwargs['revision'] == model_classifier.MODEL_REVISION


@patch('sosmed_sentiment.sentiment.model_classifier.pipeline')
def test_a_load_failure_raises_model_load_error_with_an_actionable_message(mock_pipeline_factory):
    mock_pipeline_factory.side_effect = OSError('no internet')

    with pytest.raises(ModelLoadError) as excinfo:
        model_classifier.load_model()

    assert 'internet' in str(excinfo.value) or 'koneksi' in str(excinfo.value)
    assert model_classifier.is_loaded() is False


def test_classify_before_load_model_raises():
    with pytest.raises(ModelClassifyError):
        model_classifier.classify('bagus banget')


@patch('sosmed_sentiment.sentiment.model_classifier.pipeline')
def test_positive_label_maps_to_indonesian(mock_pipeline_factory):
    mock_pipeline_factory.return_value = fake_pipeline({'label': 'LABEL_0', 'score': 0.987})
    model_classifier.load_model()

    result = model_classifier.classify('bagus banget produknya')

    assert result == {
        'sentiment_label': 'positif', 'sentiment_confidence': 0.987, 'sentiment_method': 'model'
    }


@patch('sosmed_sentiment.sentiment.model_classifier.pipeline')
def test_negative_and_neutral_labels_map_too(mock_pipeline_factory):
    mock_pipeline_factory.return_value = fake_pipeline({'label': 'LABEL_2', 'score': 0.8})
    model_classifier.load_model()
    assert model_classifier.classify('jelek parah')['sentiment_label'] == 'negatif'

    model_classifier._PIPELINE = fake_pipeline({'label': 'LABEL_1', 'score': 0.5})
    assert model_classifier.classify('biasa aja')['sentiment_label'] == 'netral'


@patch('sosmed_sentiment.sentiment.model_classifier.pipeline')
def test_an_unrecognized_label_raises_model_classify_error(mock_pipeline_factory):
    mock_pipeline_factory.return_value = fake_pipeline({'label': 'sangat_positif', 'score': 0.9})
    model_classifier.load_model()

    with pytest.raises(ModelClassifyError):
        model_classifier.classify('apapun')


@patch('sosmed_sentiment.sentiment.model_classifier.pipeline')
def test_empty_or_whitespace_input_short_circuits_to_neutral_without_calling_the_model(
    mock_pipeline_factory
):
    pipe = fake_pipeline({'label': 'positive', 'score': 0.9})
    mock_pipeline_factory.return_value = pipe
    model_classifier.load_model()

    result = model_classifier.classify('   ')

    assert result['sentiment_label'] == 'netral'
    assert result['sentiment_method'] == 'model'
    pipe.assert_not_called()


@patch('sosmed_sentiment.sentiment.model_classifier.pipeline')
def test_a_model_inference_exception_is_isolated_as_model_classify_error(mock_pipeline_factory):
    pipe = MagicMock(side_effect=RuntimeError('CUDA out of memory'))
    mock_pipeline_factory.return_value = pipe
    model_classifier.load_model()

    with pytest.raises(ModelClassifyError):
        model_classifier.classify('komentar yang bikin model meledak')


@patch('sosmed_sentiment.sentiment.model_classifier.pipeline')
def test_classify_passes_truncation_for_long_input(mock_pipeline_factory):
    pipe = fake_pipeline({'label': 'LABEL_1', 'score': 0.5})
    mock_pipeline_factory.return_value = pipe
    model_classifier.load_model()

    model_classifier.classify('kata ' * 1000)

    _, kwargs = pipe.call_args
    assert kwargs['truncation'] is True
    assert kwargs['max_length'] == model_classifier.MAX_TOKEN_LENGTH
