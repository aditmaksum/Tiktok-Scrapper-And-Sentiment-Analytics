import csv

from typing import Dict, List, Optional, Tuple

from loguru import logger

DEFAULT_LEXICON_VERSION: str = 'starter-id-v0.1'

# Ships as a starting point only - Architecture.md §2 names InSet (or an
# equivalent published Indonesian lexicon) as the intended source. This is a
# small hand-picked set covering common sentiment words and TikTok-adjacent
# slang, not a replacement for a properly sourced lexicon. Swap the file
# passed to load_lexicon() for a fuller one without touching this module -
# the format (word,score) is all this code depends on.
STARTER_LEXICON: Dict[str, float] = {
    'bagus': 0.8, 'baguus': 0.8, 'mantap': 0.9, 'keren': 0.8, 'suka': 0.7,
    'senang': 0.7, 'senangnya': 0.7, 'puas': 0.6, 'recommended': 0.7,
    'cocok': 0.6, 'membantu': 0.7, 'sembuh': 0.8, 'aman': 0.5, 'terbaik': 0.9,
    'jelek': -0.8, 'buruk': -0.8, 'parah': -0.7, 'kecewa': -0.8,
    'mahal': -0.5, 'lambat': -0.5, 'gagal': -0.7, 'rusak': -0.7,
    'bohong': -0.8, 'penipu': -0.9, 'palsu': -0.7, 'nyesel': -0.7,
    'sakit': -0.4, 'alergi': -0.5, 'ruam': -0.5,
}


def load_lexicon(
    path: str
) -> Dict[str, float]:
    """Read a word,score CSV into a lookup dict.

    Score is expected on a -1..1 scale (Architecture.md ADR-02) already
    normalised by whoever produced the lexicon file.
    """
    lexicon: Dict[str, float] = {}

    with open(path, encoding='utf-8') as handle:
        for row in csv.reader(handle):
            if len(row) < 2:
                continue
            word, score = row[0].strip(), row[1].strip()
            if not word:
                continue
            try:
                lexicon[word] = float(score)
            except ValueError:
                logger.warning('%s: skipping unreadable score %r for %r' % (path, score, word))

    return lexicon


def get_lexicon(
    path: Optional[str]
) -> Dict[str, float]:
    """STARTER_LEXICON when no config is given, otherwise the file at path.

    Same "load config with an explicit default" pattern as Rules.md §6.
    """
    if not path:
        logger.info('no lexicon config given - using the built-in starter lexicon')
        return dict(STARTER_LEXICON)

    return load_lexicon(path)


def score_tokens(
    tokens: List[str],
    lexicon: Dict[str, float]
) -> Tuple[float, float]:
    """Average lexicon score and out-of-vocabulary ratio for one comment's tokens.

    Returns (score, oov_ratio). An empty token list scores 0.0 (netral) with
    oov_ratio 0.0 - there is nothing to be out-of-vocabulary about.
    """
    if not tokens:
        return 0.0, 0.0

    matched: List[float] = [lexicon[token] for token in tokens if token in lexicon]
    oov_ratio: float = 1.0 - (len(matched) / len(tokens))
    score: float = sum(matched) / len(matched) if matched else 0.0

    return round(score, 4), round(oov_ratio, 4)


def classify(
    tokens: List[str],
    lexicon: Dict[str, float],
    neutral_band: float = 0.15
) -> Dict[str, object]:
    """Label + confidence for one comment, lexicon-only (slice 1: no LLM layer yet).

    A score inside +/-neutral_band is netral, not "ambiguous" - the
    ambiguous-vs-confident distinction that drives LLM escalation belongs to
    sentiment.hybrid (not built in this vertical slice, see design doc
    Approach B), which will read the same score/oov_ratio this function
    already returns rather than needing this function to change shape later.
    """
    score, oov_ratio = score_tokens(tokens, lexicon)

    if score > neutral_band:
        label: str = 'positif'
    elif score < -neutral_band:
        label = 'negatif'
    else:
        label = 'netral'

    confidence: float = min(abs(score) / max(neutral_band, 0.01), 1.0) if label != 'netral' else round(1.0 - abs(score), 4)

    return {
        'sentiment_label': label,
        'sentiment_confidence': round(confidence, 4),
        'sentiment_method': 'lexicon',
        'lexicon_score': score,
        'oov_ratio': oov_ratio
    }
