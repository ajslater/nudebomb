"""TVDB API lookup for TV series language detection."""

from __future__ import annotations

from threading import Lock
from typing import TYPE_CHECKING, Final

import tvdb_v4_official
from loguru import logger

from nudebomb.langfiles import lang_to_alpha3
from nudebomb.log import LOOKUP_HIT_LEVEL
from nudebomb.log.reporter import Reporter
from nudebomb.lookup.cache import LookupCache
from nudebomb.lookup.parser import parse_title

if TYPE_CHECKING:
    from pathlib import Path

    from confuse import AttrDict

    from nudebomb.lookup.parser import ParseResult

# Loose rate-limit heuristics: TVDB surfaces errors as ``{"code": int,
# "message": str}`` rather than raising. A 4xx/5xx code is treated as an
# error; a 429 specifically is rate-limited.
_RATE_LIMIT_STATUS: Final = 429
_HTTP_ERROR_MIN: Final = 400


def _is_tvdb_error_dict(result: object) -> bool:
    """Return True if a TVDB result looks like an error envelope."""
    return (
        isinstance(result, dict)
        and "code" in result
        and isinstance(result.get("code"), int)  # ty: ignore[invalid-argument-type]
        and result["code"] >= _HTTP_ERROR_MIN  # ty: ignore[invalid-argument-type,unsupported-operator]
    )


class TVDBLookup:
    """Look up original language of TV series from TVDB."""

    def __init__(self, config: AttrDict, reporter: Reporter | None = None) -> None:
        """Initialize."""
        self._tvdb = tvdb_v4_official.TVDB(config.tvdb_api_key)
        # tvdb_v4_official stores pagination state on the shared Request
        # object; serialize HTTP calls to keep that state consistent.
        self._tvdb_lock: Lock = Lock()
        self._reporter: Reporter = reporter if reporter is not None else Reporter()
        self._cache = LookupCache(config.cache_expiry_days, self._reporter)

    @staticmethod
    def _resolve_language(result: dict) -> str | None:
        """Extract and convert language from a TVDB result."""
        # Search results use "primary_language", series detail uses "originalLanguage"
        lang = result.get("primary_language") or result.get("originalLanguage") or ""
        if not lang:
            return None
        return lang_to_alpha3(lang)

    def _search_tvdb(self, title: str) -> dict | None:
        """Search TVDB for a TV series by title."""
        with self._tvdb_lock:
            results = self._tvdb.search(title, type="series")
        if not results:
            return None
        return results[0]

    def _lookup_by_id(self, tvdb_id: str) -> dict | None:
        """Look up a TV series directly by TVDB ID."""
        with self._tvdb_lock:
            result = self._tvdb.get_series(int(tvdb_id))
        if not result:
            return None
        return result

    @staticmethod
    def _extract_db_id(result: dict) -> str:
        """Extract the database ID from a TVDB result."""
        return str(result.get("id", ""))

    def _query_api(self, title: str, parsed: ParseResult) -> dict | None:
        """
        Query TVDB API.

        Returns:
        - a dict on hit
        - ``None`` on no-result (cache as a miss)
        - ``{}`` on rate-limit or error (do not cache — retry next run)

        """
        try:
            result: dict | None
            if parsed.tvdb_id:
                result = self._lookup_by_id(parsed.tvdb_id)
            else:
                result = self._search_tvdb(title)
        except Exception as exc:
            msg = f"TVDB lookup failed for '{title}': {exc}"
            logger.error(msg)
            self._reporter.progress.mark_lookup_error()
            self._reporter.stats.record_db_remote_error(msg)
            return {}

        # TVDB doesn't raise on HTTP errors — it returns a dict with
        # ``code`` and ``message`` keys. Treat those as an error just like
        # TMDB's HTTPError path.
        if _is_tvdb_error_dict(result):
            assert isinstance(result, dict)
            code = result.get("code", 0)
            err_msg = result.get("message", "")
            label = parsed.tvdb_id or title or "(unknown)"
            if code == _RATE_LIMIT_STATUS:
                msg = f"TVDB rate limited for '{label}': {err_msg}"
                logger.warning(msg)
                self._reporter.progress.mark_lookup_rate_limited()
            else:
                msg = f"TVDB HTTP error {code} for '{label}': {err_msg}"
                logger.error(msg)
                self._reporter.progress.mark_lookup_error()
            self._reporter.stats.record_db_remote_error(msg)
            return {}

        return result

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

    def _lookup_by_id_language(self, parsed: ParseResult) -> str | None:
        """Look up language by TVDB ID, bypassing title-based caching."""
        if parsed.tvdb_id:
            found, cached_lang = self._cache.check_id_cache(
                "tv", "tvdb", parsed.tvdb_id
            )
            if found:
                return cached_lang

        result = self._query_api("", parsed)
        if result == {}:
            return None
        label = f"TVDB ID {parsed.tvdb_id}"
        if not result:
            self._record_remote_no_result(label)
            return None

        lang = self._resolve_language(result) or ""
        if parsed.tvdb_id:
            self._cache.save_id(
                "tv",
                "tvdb",
                parsed.tvdb_id,
                db_id=self._extract_db_id(result),
                language=lang,
            )

        if lang:
            self._record_remote_hit(label, lang)
        else:
            self._record_remote_no_result(label)
        return lang or None

    def _lookup_by_title_language(self, title: str, parsed: ParseResult) -> str | None:
        """Look up language by title search with caching."""
        found, lang = self._cache.check_cache("tv", title, "")
        if found:
            return lang

        result = self._query_api(title, parsed)
        if result == {}:
            return None

        if result is not None:
            lang = self._resolve_language(result) or ""
            self._cache.save_file(
                "tv",
                title,
                "",
                db_id=self._extract_db_id(result),
                language=lang,
            )
        else:
            self._cache.save_file("tv", title, "")
            lang = ""

        self._cache.set_mem("tv", title, "", lang or None)
        label = f"TVDB: '{title}'"
        if lang:
            self._record_remote_hit(label, lang)
        else:
            self._record_remote_no_result(label)
        return lang or None

    def lookup_language(self, path: Path) -> str | None:
        """
        Look up the original language for a TV series file.

        Returns an ISO 639-3 language code (or ``None``). All log /
        progress / stats side effects happen inline.
        """
        parsed = parse_title(path.stem, "tv")

        if parsed.tvdb_id:
            return self._lookup_by_id_language(parsed)

        if not parsed.title:
            return None

        return self._lookup_by_title_language(parsed.title, parsed)
