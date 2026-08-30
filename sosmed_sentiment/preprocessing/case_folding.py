def case_fold(
    text: str
) -> str:
    """Second stage (PRD.md FR-03 order), after emoji extraction.

    str.casefold() rather than str.lower() - casefold is the stdlib's
    Unicode-aware full case folding, a stricter guarantee than lower() for
    text that may contain non-ASCII letters.
    """
    return (text or '').casefold()
