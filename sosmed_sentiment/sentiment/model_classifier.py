from typing import Any, Dict, Optional

from loguru import logger
from transformers import pipeline

from sosmed_sentiment.errors import ModelClassifyError, ModelLoadError

# w11wo/indonesian-roberta-base-sentiment-classifier (the design doc's original
# pick) was measured at 53.5% accuracy against the Tahap B 200-comment labeled
# sample - below the netral-only baseline (69%) and the G-08 target (80%),
# with a systematic bias toward "negatif" on short/casual/emoji-only TikTok
# comments (its SmSA training data is formal app reviews). Swapped after
# comparing candidates directly against the same labeled sample
# (scripts/compare_models.py) rather than trusting a model card in isolation -
# same measure-before-trusting discipline as the Sastrawi/LLM-cost findings.
MODEL_NAME: str = 'mdhugol/indonesia-bert-sentiment-classification'
# IndoBERT fine-tuned on the same IndoNLU/Prosa SMSA dataset as w11wo, but
# generalizes far better here: 71.0% raw accuracy vs w11wo's 53.5%, and no
# negatif bias (confusion matrix is diagonally balanced). Pinned to a specific
# commit - verified against the model repo's own commit history (autoplan Eng
# #9: reproducibility). A HuggingFace weight update after this point cannot
# silently change results.
MODEL_REVISION: str = '80ccb4c2817cf976534ac491020a9572e5dae54f'
MAX_TOKEN_LENGTH: int = 512

# This model's config.json ships generic id2label ({'0': 'LABEL_0', ...}) -
# the mapping below is the repo's own documented order (its README's usage
# example), not inferred from label text like w11wo's model - verified
# directly against this repo's labeled sample (scripts/compare_models.py),
# not just copied from the model card.
LABEL_TO_INDO: Dict[str, str] = {
    'label_0': 'positif',
    'label_1': 'netral',
    'label_2': 'negatif',
}

_PIPELINE: Optional[Any] = None


def load_model() -> None:
    """Load the model+tokenizer once, at process start (not per comment).

    Called explicitly by cli.analyze before the comment loop - a failure
    here (no internet, HF down, disk space) happens before a single comment
    is processed, so a rerun once the issue is fixed loses no work
    (decision recorded in docs/plans/2026-08-30-model-cascade-implementation.md,
    "no-fallback-offline risk accepted").
    """
    global _PIPELINE
    if _PIPELINE is not None:
        return

    logger.info(
        'memuat model sentimen lokal (%s)... unduhan pertama kali ~500MB, '
        'sekali per mesin, butuh internet - proses berikutnya pakai cache lokal.'
        % MODEL_NAME
    )
    try:
        _PIPELINE = pipeline(
            'sentiment-analysis',
            model=MODEL_NAME,
            revision=MODEL_REVISION,
            truncation=True,
            max_length=MAX_TOKEN_LENGTH,
        )
    except Exception as error:  # noqa: BLE001 - any load failure becomes one actionable message
        raise ModelLoadError(
            'gagal memuat model sentimen lokal (%s @ %s): %s. Cek koneksi internet '
            '(unduhan pertama kali ~500MB) atau proxy/firewall kantor yang memblokir '
            'huggingface.co.' % (MODEL_NAME, MODEL_REVISION[:12], error)
        ) from error

    logger.info('model sentimen lokal siap dipakai.')


def is_loaded() -> bool:
    return _PIPELINE is not None


def classify(
    text_raw: str
) -> Dict[str, Any]:
    """One comment's raw text -> {sentiment_label, sentiment_confidence, sentiment_method}.

    Takes text_raw, not preprocessed tokens - the model has its own subword
    tokenizer and does not need the 7-stage preprocessing pipeline built for
    the lexicon path (design doc, section 2).

    Raises ModelClassifyError for a single comment's failure (OOM, unexpected
    label, etc) - sentiment.hybrid catches this and falls through to LLM
    escalation rather than letting one comment abort the batch.
    """
    if _PIPELINE is None:
        raise ModelClassifyError('load_model() belum dipanggil sebelum classify()')

    stripped: str = (text_raw or '').strip()
    if not stripped:
        # Nothing to classify - not a model failure, a defined empty case.
        return {'sentiment_label': 'netral', 'sentiment_confidence': 1.0, 'sentiment_method': 'model'}

    try:
        prediction: Dict[str, Any] = _PIPELINE(text_raw, truncation=True, max_length=MAX_TOKEN_LENGTH)[0]
    except Exception as error:  # noqa: BLE001 - isolate this one comment, never the batch
        raise ModelClassifyError('model classify gagal untuk satu komentar: %s' % error) from error

    raw_label: str = str(prediction['label']).lower()
    label: Optional[str] = LABEL_TO_INDO.get(raw_label)
    if label is None:
        raise ModelClassifyError('label model tidak dikenal: %r' % prediction['label'])

    return {
        'sentiment_label': label,
        'sentiment_confidence': round(float(prediction['score']), 4),
        'sentiment_method': 'model'
    }
