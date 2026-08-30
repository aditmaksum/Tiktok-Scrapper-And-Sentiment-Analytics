from sosmed_sentiment.sentiment.hybrid import (
    DEFAULT_AMBIGUOUS_THRESHOLD_OOV_RATIO, DEFAULT_AMBIGUOUS_THRESHOLD_SCORE
)
from sosmed_sentiment.sentiment.threshold_config import load_threshold_config


def test_no_path_returns_the_hybrid_defaults():
    score, oov = load_threshold_config(None)

    assert score == DEFAULT_AMBIGUOUS_THRESHOLD_SCORE
    assert oov == DEFAULT_AMBIGUOUS_THRESHOLD_OOV_RATIO


def test_a_config_file_overrides_the_defaults(tmp_path):
    path = tmp_path / 'thresholds.yaml'
    path.write_text('ambiguous_threshold_score: 0.3\nambiguous_threshold_oov_ratio: 0.7\n', encoding='utf-8')

    score, oov = load_threshold_config(str(path))

    assert score == 0.3
    assert oov == 0.7


def test_a_partial_config_falls_back_for_the_missing_key(tmp_path):
    path = tmp_path / 'thresholds.yaml'
    path.write_text('ambiguous_threshold_score: 0.25\n', encoding='utf-8')

    score, oov = load_threshold_config(str(path))

    assert score == 0.25
    assert oov == DEFAULT_AMBIGUOUS_THRESHOLD_OOV_RATIO
