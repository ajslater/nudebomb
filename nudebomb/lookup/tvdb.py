"""TVDB API lookup for TV series language detection."""

from __future__ import annotations

import socket
from threading import Lock
from typing import TYPE_CHECKING, Final

import tvdb_v4_official
from loguru import logger

from nudebomb.lang import lang_to_alpha3
from nudebomb.lookup.base import QUERY_ERROR, BaseLookup, QueryOutcome
from nudebomb.lookup.parser import parse_title
from nudebomb.lookup.util import LOOKUP_TIMEOUT_SECONDS, best_title_match

if TYPE_CHECKING:
    from pathlib import Path

    from nudebomb.config import NudebombSettings
    from nudebomb.log.reporter import Reporter
    from nudebomb.lookup.cache import LookupCache
    from nudebomb.lookup.parser import ParseResult

# Loose rate-limit heuristics: TVDB surfaces errors as ``{"code": int,
# "message": str}`` rather than raising. A 4xx/5xx code is treated as an
# error; a 429 specifically is rate-limited.
_RATE_LIMIT_STATUS: Final = 429
_HTTP_ERROR_MIN: Final = 400


def _result_titles(result: dict) -> list[str]:
    """
    Every candidate name for a TVDB search result.

    Includes aliases and translated names so a romanized query still
    matches a show whose canonical TVDB name is non-Latin (e.g. a show
    stored in katakana but named on disk in romaji).
    """
    titles: list[str] = []
    for key in ("name", "title"):
        value = result.get(key)
        if isinstance(value, str):
            titles.append(value)
    aliases = result.get("aliases")
    if isinstance(aliases, list):
        titles.extend(alias for alias in aliases if isinstance(alias, str))
    translations = result.get("translations")
    if isinstance(translations, dict):
        titles.extend(name for name in translations.values() if isinstance(name, str))
    return titles


def _result_year(result: dict) -> str:
    """Year field for a TVDB search result."""
    return str(result.get("year") or "")


def _is_tvdb_error_dict(result: object) -> bool:
    """Return True if a TVDB result looks like an error envelope."""
    return (
        isinstance(result, dict)
        and "code" in result
        and isinstance(result.get("code"), int)
        and result["code"] >= _HTTP_ERROR_MIN  # ty: ignore[invalid-argument-type,unsupported-operator]
    )


class TVDBLookup(BaseLookup):
    """Look up original language of TV series from TVDB."""

    def __init__(
        self,
        config: NudebombSettings,
        reporter: Reporter | None = None,
        cache: LookupCache | None = None,
    ) -> None:
        """Initialize."""
        if not config.tvdb_api_key:
            msg = "TVDBLookup requires a tvdb_api_key in config"
            raise ValueError(msg)
        # tvdb_v4_official uses bare urllib.request.urlopen with no
        # timeout parameter; the process-wide socket default is the only
        # way to bound it (covers the login POST below too). Otherwise a
        # stalled connection hangs the whole run.
        socket.setdefaulttimeout(LOOKUP_TIMEOUT_SECONDS)
        self._tvdb = tvdb_v4_official.TVDB(config.tvdb_api_key)
        # tvdb_v4_official stores pagination state on the shared Request
        # object; serialize HTTP calls to keep that state consistent.
        self._tvdb_lock: Lock = Lock()
        super().__init__(config, reporter, cache)

    @staticmethod
    def _resolve_language(result: dict) -> str | None:
        """Extract and convert language from a TVDB result."""
        # Search results use "primary_language", series detail uses "originalLanguage"
        lang = result.get("primary_language") or result.get("originalLanguage") or ""
        if not lang:
            return None
        return lang_to_alpha3(lang)

    def _search_tvdb(self, title: str, year: str = "") -> dict | None:
        """Search TVDB for a TV series by title."""
        with self._tvdb_lock:
            results = self._tvdb.search(title, type="series")
        if not results:
            return None
        return best_title_match(results, title, year, _result_titles, _result_year)

    def _lookup_by_id(self, tvdb_id: str) -> dict | None:
        """Look up a TV series directly by TVDB ID."""
        with self._tvdb_lock:
            result = self._tvdb.get_series(int(tvdb_id))
        if not result:
            return None
        return result

    def _query_api(self, title: str, parsed: ParseResult) -> QueryOutcome:
        """Query TVDB API."""
        try:
            result: dict | None
            if parsed.tvdb_id:
                result = self._lookup_by_id(parsed.tvdb_id)
            else:
                # The parsed year doesn't participate in the search or the
                # cache key, but it disambiguates remakes when verifying
                # the result title.
                result = self._search_tvdb(title, parsed.year)
        except Exception as exc:
            msg = f"TVDB lookup failed for '{title}': {exc}"
            logger.error(msg)
            self._reporter.progress.mark_lookup_error()
            self._reporter.stats.record_db_remote_error(msg)
            return QUERY_ERROR

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
            return QUERY_ERROR

        return QueryOutcome(result=result)

    def _lookup_by_id_language(self, parsed: ParseResult) -> str | None:
        """Look up language by TVDB ID, bypassing title-based caching."""
        if parsed.tvdb_id:
            found, cached_lang = self._cache.check_id_cache(
                "tv", "tvdb", parsed.tvdb_id
            )
            if found:
                return cached_lang

        outcome = self._query_api("", parsed)
        if outcome.error:
            return None
        result = outcome.result
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

        outcome = self._query_api(title, parsed)
        if outcome.error:
            return None

        result = outcome.result
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
