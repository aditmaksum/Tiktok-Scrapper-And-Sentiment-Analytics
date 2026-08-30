import re

from typing import List, Tuple

# Common emoji blocks (emoticons, symbols & pictographs, transport, dingbats,
# supplemental symbols, flags). Not exhaustive, but stdlib-only (re module)
# per the reuse ladder - no third-party emoji package needed for this.
EMOJI_PATTERN: re.Pattern = re.compile(
    '['
    '\U0001F300-\U0001F5FF'
    '\U0001F600-\U0001F64F'
    '\U0001F680-\U0001F6FF'
    '\U0001F900-\U0001F9FF'
    '\U0001FA70-\U0001FAFF'
    '\U00002600-\U000026FF'
    '\U00002700-\U000027BF'
    ']'
)


def extract_emoji(
    text: str
) -> Tuple[str, List[str]]:
    """Pull emoji out of text before any other preprocessing stage runs.

    Runs first (PRD.md FR-03 order) because later stages - case folding,
    cleaning - are defined over regular text and would otherwise mangle
    multi-codepoint emoji sequences.

    Returns (text_without_emoji, list_of_emoji_found) - the list becomes
    Schema.md §3's `emoji_found` field, kept separate from the token stream.
    """
    found: List[str] = list(EMOJI_PATTERN.findall(text or ''))
    stripped: str = EMOJI_PATTERN.sub('', text or '')

    return stripped, found
