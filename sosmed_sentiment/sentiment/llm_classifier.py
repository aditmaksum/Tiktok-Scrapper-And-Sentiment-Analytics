import json
import os
import time

from typing import Any, Dict, Optional

from loguru import logger
from openai import OpenAI

from sosmed_sentiment.errors import LLMCallError

MAX_RETRIES: int = 2
RETRY_BACKOFF_SECONDS: tuple = (1, 3)

SYSTEM_PROMPT: str = (
    'Anda mengklasifikasikan sentimen komentar sosial media berbahasa '
    'Indonesia (termasuk slang TikTok). Balas HANYA dengan JSON persis '
    'berformat {"label": "positif"|"negatif"|"netral", "confidence": angka '
    '0..1}. Jangan balas apapun selain JSON itu.'
)


def _client(
    base_url: Optional[str],
    api_key: Optional[str]
) -> OpenAI:
    """One OpenAI-compatible client, base_url swappable per Premise 3 (router-agnostic).

    api_key/base_url read from env by the caller (LLM_API_KEY, LLM_BASE_URL)
    - never hardcoded, never logged (Rules.md §7).
    """
    return OpenAI(api_key=api_key, base_url=base_url or None)


def classify_via_llm(
    text: str,
    model: str,
    base_url: Optional[str] = None,
    api_key: Optional[str] = None
) -> Dict[str, Any]:
    """One comment -> {sentiment_label, sentiment_confidence, sentiment_method}.

    Retries up to MAX_RETRIES times with backoff (Architecture.md §8) before
    raising LLMCallError - the caller (sentiment.hybrid, not built in this
    vertical slice) is expected to catch that and mark the comment
    llm_failed rather than let one comment fail the whole batch.
    """
    client: OpenAI = _client(base_url, api_key or os.environ.get('LLM_API_KEY'))
    last_error: Optional[Exception] = None

    for attempt in range(1, MAX_RETRIES + 2):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {'role': 'system', 'content': SYSTEM_PROMPT},
                    {'role': 'user', 'content': text}
                ],
                temperature=0
            )
            content: str = response.choices[0].message.content or ''
            parsed: Dict[str, Any] = json.loads(content)

            label: str = parsed['label']
            if label not in ('positif', 'negatif', 'netral'):
                raise ValueError('unexpected label %r from LLM' % label)

            return {
                'sentiment_label': label,
                'sentiment_confidence': round(float(parsed.get('confidence', 0.5)), 4),
                'sentiment_method': 'llm'
            }
        except Exception as error:  # noqa: BLE001 - any failure here is a retry candidate
            last_error = error
            if attempt <= MAX_RETRIES:
                low, high = RETRY_BACKOFF_SECONDS
                delay = low + (high - low) * (attempt - 1) / max(MAX_RETRIES - 1, 1)
                logger.warning(
                    'LLM call failed (attempt %d/%d): %s - retrying in %.1fs'
                    % (attempt, MAX_RETRIES + 1, error, delay)
                )
                time.sleep(delay)

    raise LLMCallError('LLM call failed after %d attempts: %s' % (MAX_RETRIES + 1, last_error))
