import re

from typing import Dict

# Starter slang map for informal TikTok Indonesian - not exhaustive. Expand as
# spot checks on real batches turn up more forms (PRD.md ASUMSI: lexicon/slang
# coverage needs calibration against real data before being trusted fully).
# Never maps a word onto or away from a negation - Rules.md Aturan Mutlak.
SLANG_MAP: Dict[str, str] = {
    'gak': 'tidak', 'ga': 'tidak', 'gk': 'tidak', 'ngga': 'tidak',
    'nggak': 'tidak', 'kaga': 'tidak', 'tdk': 'tidak',
    'bgt': 'banget', 'bngt': 'banget',
    'yg': 'yang', 'dgn': 'dengan', 'dr': 'dari', 'utk': 'untuk',
    'krn': 'karena', 'karna': 'karena', 'sm': 'sama',
    'tp': 'tapi', 'jd': 'jadi', 'jgn': 'jangan', 'udh': 'sudah',
    'udah': 'sudah', 'sdh': 'sudah', 'blm': 'belum', 'blum': 'belum',
    'gmn': 'bagaimana', 'gimana': 'bagaimana', 'knp': 'kenapa',
    'org': 'orang', 'skrg': 'sekarang', 'sy': 'saya', 'gw': 'saya',
    'gue': 'saya', 'aq': 'saya', 'ak': 'saya'
}

ELONGATION_PATTERN: re.Pattern = re.compile(r'(.)\1{2,}')


def normalize(
    text: str
) -> str:
    """Fourth stage (PRD.md FR-03 order): slang -> standard form, per token.

    Collapses elongated characters first ("baguuuus" -> "baguus", still not
    a dictionary word but short enough for the stemmer/lexicon to have a
    fighting chance), then maps known slang tokens. Runs before tokenizing
    in FR-03's stage list, but token-by-token replacement needs the text
    split on whitespace here regardless - the split is discarded, not the
    tokenizing stage itself, which still runs after this to produce the
    token list the rest of the pipeline uses.
    """
    collapsed: str = ELONGATION_PATTERN.sub(r'\1\1', text or '')

    words = collapsed.split()
    mapped = [SLANG_MAP.get(word, word) for word in words]

    return ' '.join(mapped)
