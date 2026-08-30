from typing import List

from Sastrawi.Stemmer.StemmerFactory import StemmerFactory

# Sastrawi's factory does real setup work (loading its root-word dictionary),
# so it is built once per process rather than per call.
_STEMMER = StemmerFactory().create_stemmer()


def stem(
    tokens: List[str]
) -> List[str]:
    """Seventh and last stage (PRD.md FR-03 order): each token to its root form.

    PySastrawi (Architecture.md §2) - the standard Indonesian stemmer, avoids
    hand-rolling stemming rules.

    Stems the whole token list in ONE call, not one call per token. Measured
    on the real 6.158-comment batch: calling stem() per token took ~7
    minutes for 4.820 comments (Sastrawi's per-call setup cost dominates
    for single-word input - confirmed by direct measurement: ~14-140ms per
    single-word call vs ~0.15ms for 200 words stemmed as one string).
    Rejoining the token list into one string and stemming it once brought
    the same batch down to seconds. A per-token cache alone (tried first)
    did not fix this, because the vocabulary of real informal comments is
    wide enough that most tokens are still cache misses.

    Falls back to stemming token-by-token only if Sastrawi's output doesn't
    split back into the same number of words - a safety net against a
    silent token/stem misalignment, not the expected path.
    """
    if not tokens:
        return []

    stemmed_sentence: str = _STEMMER.stem(' '.join(tokens))
    stemmed_tokens: List[str] = stemmed_sentence.split()

    if len(stemmed_tokens) == len(tokens):
        return stemmed_tokens

    return [_STEMMER.stem(token) for token in tokens]
