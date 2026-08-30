from typing import Any, Dict, List, Optional

from sosmed_sentiment.errors import LLMCallError
from sosmed_sentiment.sentiment.lexicon_classifier import classify as lexicon_classify
from sosmed_sentiment.sentiment.lexicon_classifier import score_tokens
from sosmed_sentiment.sentiment.llm_classifier import classify_via_llm

DEFAULT_AMBIGUOUS_THRESHOLD_SCORE: float = 0.15
DEFAULT_AMBIGUOUS_THRESHOLD_OOV_RATIO: float = 0.5

# Architecture.md §8: past this failure ratio among escalated comments, exit
# 3 so the analyst notices a systemic problem rather than random noise.
LLM_FAILURE_EXIT_THRESHOLD: float = 0.10


def is_ambiguous(
    score: float,
    oov_ratio: float,
    threshold_score: float = DEFAULT_AMBIGUOUS_THRESHOLD_SCORE,
    threshold_oov: float = DEFAULT_AMBIGUOUS_THRESHOLD_OOV_RATIO
) -> bool:
    """Architecture.md ADR-02 escalation rule: score in the neutral band, or too OOV."""
    return abs(score) <= threshold_score or oov_ratio > threshold_oov


def classify_comment(
    tokens: List[str],
    text_raw: str,
    lexicon: Dict[str, float],
    model: str,
    base_url: Optional[str] = None,
    api_key: Optional[str] = None,
    threshold_score: float = DEFAULT_AMBIGUOUS_THRESHOLD_SCORE,
    threshold_oov: float = DEFAULT_AMBIGUOUS_THRESHOLD_OOV_RATIO
) -> Dict[str, Any]:
    """One comment through the hybrid decision (Architecture.md ADR-02).

    A clear lexicon score never calls the LLM at all - cost control is a
    branch that's never taken, not a check that runs and is overridden.
    A failed LLM call becomes tidak_terklasifikasi/llm_failed, not an
    exception that reaches the caller - Rules.md §2: one comment's failure
    never stops the batch.
    """
    score, oov_ratio = score_tokens(tokens, lexicon)

    if not is_ambiguous(score, oov_ratio, threshold_score, threshold_oov):
        return lexicon_classify(tokens, lexicon, neutral_band=threshold_score)

    try:
        return classify_via_llm(text_raw, model=model, base_url=base_url, api_key=api_key)
    except LLMCallError:
        return {
            'sentiment_label': 'tidak_terklasifikasi',
            'sentiment_confidence': 0.0,
            'sentiment_method': 'llm_failed'
        }


def llm_failure_ratio_exceeds_threshold(
    comments: List[Dict[str, Any]]
) -> bool:
    """Architecture.md §8: ratio of llm_failed among ESCALATED comments, not all comments.

    A batch that never escalates anything (100% lexicon) cannot trip this -
    the ratio is only meaningful relative to what was actually sent to the
    LLM.
    """
    escalated: int = sum(
        1 for c in comments if c['sentiment_method'] in ('llm', 'llm_failed')
    )
    if not escalated:
        return False

    failed: int = sum(1 for c in comments if c['sentiment_method'] == 'llm_failed')

    return (failed / escalated) > LLM_FAILURE_EXIT_THRESHOLD
