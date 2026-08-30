from typing import List, Optional, Set

from loguru import logger

# Never treated as stopwords, no matter what a config file says - Rules.md
# Aturan Mutlak: dropping these silently wrecks sentiment accuracy with no
# visible error, because "tidak bagus" and "bagus" would tokenize the same.
NEGATION_WORDS: frozenset = frozenset({'tidak', 'bukan', 'belum', 'jangan'})

# Small built-in fallback so the pipeline still runs without a config file -
# Schema.md §6 expects config/stopwords_custom.txt to exist before a real
# run, this is not a substitute for that, just enough to not crash.
DEFAULT_STOPWORDS: frozenset = frozenset({
    'yang', 'dan', 'di', 'ke', 'dari', 'untuk', 'dengan', 'itu', 'ini',
    'ada', 'saya', 'kamu', 'kita', 'juga', 'aja', 'saja', 'lah', 'sih',
    'nya', 'atau', 'karena', 'jadi', 'lagi', 'bisa', 'kalau', 'pada'
})


def load_stopwords(
    path: Optional[str]
) -> Set[str]:
    """Read config/stopwords_custom.txt, one word per line.

    Falls back to DEFAULT_STOPWORDS when no path is given (dry runs, tests).
    Negation words are stripped from whatever is loaded regardless of source
    - defensive even against a config file that lists them by mistake.
    """
    if not path:
        logger.info('no stopword config given - using the built-in default list')
        return set(DEFAULT_STOPWORDS) - NEGATION_WORDS

    with open(path, encoding='utf-8') as handle:
        words: Set[str] = {line.strip() for line in handle if line.strip()}

    dropped: Set[str] = words & NEGATION_WORDS
    if dropped:
        logger.warning(
            '%s lists negation word(s) %s as stopwords - ignoring them '
            '(Rules.md: negation words are never filtered)'
            % (path, ', '.join(sorted(dropped)))
        )

    return words - NEGATION_WORDS


def filter_stopwords(
    tokens: List[str],
    stopwords: Set[str]
) -> List[str]:
    """Sixth stage (PRD.md FR-03 order): drop stopwords, keep negation words.

    stopwords is expected to already exclude NEGATION_WORDS (load_stopwords
    guarantees this), so this function does not need to re-check them.
    """
    return [token for token in tokens if token not in stopwords]
