import pytest

from sosmed_sentiment.sentiment.threshold_config import load_threshold_config


def test_no_path_raises_because_no_default_is_baked_into_code():
    with pytest.raises(ValueError):
        load_threshold_config(None)


def test_a_config_file_returns_the_calibrated_threshold(tmp_path):
    path = tmp_path / 'thresholds.yaml'
    path.write_text('ambiguous_confidence_threshold: 0.62\n', encoding='utf-8')

    threshold = load_threshold_config(str(path))

    assert threshold == 0.62


def test_a_config_missing_the_key_raises(tmp_path):
    path = tmp_path / 'thresholds.yaml'
    path.write_text('some_other_key: 1\n', encoding='utf-8')

    with pytest.raises(ValueError):
        load_threshold_config(str(path))
