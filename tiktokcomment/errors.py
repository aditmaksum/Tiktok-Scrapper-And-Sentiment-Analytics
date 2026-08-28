class ScrapeError(Exception):
    """Base error for every failure the scraper reports to the operator."""

class BlockedError(ScrapeError):
    """TikTok answered with something that is not comment JSON.

    Raised for non-2xx status, an empty body, or an HTML block/captcha page.
    This is the signature that the unsigned endpoint stopped working.
    """

class SchemaError(ScrapeError):
    """The response parsed as JSON but no longer matches the expected shape."""
