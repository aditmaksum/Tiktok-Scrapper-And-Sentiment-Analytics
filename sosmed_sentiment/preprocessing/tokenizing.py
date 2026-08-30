import re

from typing import List

TOKEN_PATTERN: re.Pattern = re.compile(r"[a-z0-9']+")


def tokenize(
    text: str
) -> List[str]:
    """Fifth stage (PRD.md FR-03 order): text -> list of word tokens.

    Runs after normalize() so slang has already been mapped to its standard
    form as whole words; splitting here just needs to isolate word
    characters, punctuation carries no separate meaning at this stage.
    """
    return TOKEN_PATTERN.findall(text or '')
