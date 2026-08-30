from abc import ABC, abstractmethod
from typing import Any, Dict, List


class PlatformAdapter(ABC):
    """One method every platform's ingest module must provide.

    A future adapter (Instagram, X, YouTube) implements this against its own
    raw export shape; no other component needs to change, because everything
    downstream of ingest only ever sees the flat record shape this method
    returns (Schema.md §3). Not built for any platform beyond TikTok yet -
    this interface exists so that day doesn't require touching filters,
    preprocessing, or sentiment.
    """

    @abstractmethod
    def flatten(
        self: 'PlatformAdapter',
        raw: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Validate raw platform export, return one flat dict per comment/reply.

        Raises InvalidInputSchemaError (see errors.py) on any structural
        violation, naming the offending video/comment id. Never returns a
        partial result for invalid input - Rules.md §7: schema errors always
        stop the run, they are never skipped quietly.
        """
