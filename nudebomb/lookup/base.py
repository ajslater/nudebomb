"""Shared plumbing for the TMDB/TVDB lookup backends."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from loguru import logger

from nudebomb.log import LOOKUP_HIT_LEVEL
from nudebomb.log.reporter import Reporter
from nudebomb.lookup.cache import LookupCache

if TYPE_CHECKING:
    from nudebomb.config import NudebombSettings

__all__ = ("QUERY_ERROR", "BaseLookup", "QueryOutcome")


@dataclass(frozen=True, slots=True)
class QueryOutcome:
    """
    Outcome of one remote API query.

    ``error`` means rate-limited or failed — do not cache, retry next
    run. Otherwise ``result`` is the API payload, or None for a genuine
    no-result (cacheable as a miss).
    """

    result: dict | None = None
    error: bool = False


QUERY_ERROR = QueryOutcome(error=True)


class BaseLookup:
    """Reporter/cache wiring and log/stats helpers shared by backends."""

    def __init__(
        self,
        config: NudebombSettings,
        reporter: Reporter | None = None,
        cache: LookupCache | None = None,
    ) -> None:
        """Initialize reporting sinks and the lookup cache."""
        self._reporter: Reporter = reporter if reporter is not None else Reporter()
        self._cache: LookupCache = (
            cache
            if cache is not None
            else LookupCache(config.cache_expiry_days, self._reporter)
        )

    @staticmethod
    def _extract_db_id(result: dict) -> str:
        """Extract the database ID from an API result."""
        return str(result.get("id", ""))

    def _record_remote_hit(self, label: str, lang: str) -> None:
        """Record a successful remote lookup with a language."""
        logger.log(LOOKUP_HIT_LEVEL, f"{label}: original language: {lang}")
        self._reporter.progress.mark_lookup_hit()
        self._reporter.stats.record_db_remote_hit()

    def _record_remote_no_result(self, label: str) -> None:
        """Record a remote lookup that returned no result."""
        msg = f"{label}: no result found"
        logger.warning(msg)
        self._reporter.progress.mark_lookup_no_result()
        self._reporter.stats.record_db_no_result(msg)
