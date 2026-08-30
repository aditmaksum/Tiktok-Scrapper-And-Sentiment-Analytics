import re

URL_PATTERN: re.Pattern = re.compile(r'https?://\S+|www\.\S+')
MENTION_PATTERN: re.Pattern = re.compile(r'@\w+')
WHITESPACE_PATTERN: re.Pattern = re.compile(r'\s+')


def clean(
    text: str
) -> str:
    """Third stage (PRD.md FR-03 order): strip noise that carries no sentiment.

    Removes URLs and @mentions (neither expresses an opinion) and collapses
    whitespace. Runs after case_folding, before normalizing - normalizing
    works on words, not on noise tokens like raw URLs.
    """
    result: str = URL_PATTERN.sub(' ', text or '')
    result = MENTION_PATTERN.sub(' ', result)
    result = WHITESPACE_PATTERN.sub(' ', result)

    return result.strip()
