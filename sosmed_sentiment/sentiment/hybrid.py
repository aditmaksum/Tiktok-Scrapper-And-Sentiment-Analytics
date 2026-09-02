from typing import Any, Dict, List, Optional

from loguru import logger

from sosmed_sentiment.errors import LLMCallError, ModelClassifyError
from sosmed_sentiment.sentiment.llm_classifier import classify_via_llm
from sosmed_sentiment.sentiment.model_classifier import classify as model_classify

# Architecture.md §8: past this failure ratio among escalated comments, exit
# 3 so the analyst notices a systemic problem rather than random noise.
LLM_FAILURE_EXIT_THRESHOLD: float = 0.10


def is_ambiguous(
    confidence: float,
    threshold: float
) -> bool:
    """docs/designs/sentiment-model-cascade.md Feasibility Note: a classifier model
    returns one confidence value, not a signed score + OOV ratio - the two-signal
    lexicon gate this replaced does not apply. Below threshold -> escalate to LLM.
    """
    return confidence < threshold


def classify_comment(
    text_raw: str,
    llm_model: str,
    threshold_confidence: float,
    base_url: Optional[str] = None,
    api_key: Optional[str] = None
) -> Dict[str, Any]:
    """One comment through the model->LLM cascade (design doc Approach C).

    The local model is the cheap first pass; low-confidence results escalate
    to the LLM. A model failure on one comment (ModelClassifyError) also
    escalates rather than aborting the batch - the LLM layer already has to
    handle isolation for its own failures, so a model failure just means
    "treat as maximally ambiguous" instead of adding a second failure path.
    A failed LLM call becomes tidak_terklasifikasi/llm_failed, not an
    exception that reaches the caller - Rules.md §2: one comment's failure
    never stops the batch.
    """
    try:
        result: Optional[Dict[str, Any]] = model_classify(text_raw)
    except ModelClassifyError as error:
        logger.warning('model classify gagal untuk satu komentar, eskalasi ke LLM: %s' % error)
        result = None

    if result is not None and not is_ambiguous(result['sentiment_confidence'], threshold_confidence):
        return result

    try:
        return classify_via_llm(text_raw, model=llm_model, base_url=base_url, api_key=api_key)
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

    A batch that never escalates anything cannot trip this - the ratio is
    only meaningful relative to what was actually sent to the LLM.
    """
    escalated: int = sum(
        1 for c in comments if c['sentiment_method'] in ('llm', 'llm_failed')
    )
    if not escalated:
        return False

    failed: int = sum(1 for c in comments if c['sentiment_method'] == 'llm_failed')

    return (failed / escalated) > LLM_FAILURE_EXIT_THRESHOLD
