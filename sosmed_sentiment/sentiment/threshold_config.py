from typing import Optional, Tuple

import yaml

from loguru import logger

from sosmed_sentiment.sentiment.hybrid import (
    DEFAULT_AMBIGUOUS_THRESHOLD_OOV_RATIO, DEFAULT_AMBIGUOUS_THRESHOLD_SCORE
)


def load_threshold_config(
    path: Optional[str]
) -> Tuple[float, float]:
    """(threshold_score, threshold_oov_ratio), Rules.md §6 default-config pattern.

    Both values are explicitly flagged in PRD.md §9 as uncalibrated defaults
    - this is where an analyst overrides them after reviewing a real run's
    escalation ratio, without editing code.
    """
    if not path:
        logger.info('no threshold config given, pakai default bawaan')
        return DEFAULT_AMBIGUOUS_THRESHOLD_SCORE, DEFAULT_AMBIGUOUS_THRESHOLD_OOV_RATIO

    with open(path, encoding='utf-8') as handle:
        data = yaml.safe_load(handle) or {}

    return (
        float(data.get('ambiguous_threshold_score', DEFAULT_AMBIGUOUS_THRESHOLD_SCORE)),
        float(data.get('ambiguous_threshold_oov_ratio', DEFAULT_AMBIGUOUS_THRESHOLD_OOV_RATIO))
    )
