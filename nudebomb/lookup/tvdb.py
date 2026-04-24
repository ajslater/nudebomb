"""TVDB API lookup for TV series language detection."""

from pathlib import Path
from threading import Lock
from typing import Final

import tvdb_v4_official
from confuse import AttrDict

from nudebomb.langfiles import lang_to_alpha3
from nudebomb.lookup.cache import LookupCache
from nudebomb.lookup.parser import ParseResult, parse_title
from nudebomb.lookup.util import LogEvent, LookupResult

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
        and isinstance(result.get("code"), int)
        and result["code"] >= _HTTP_ERROR_MIN
    )


class TVDBLookup:
    """Look up original language of TV series from TVDB."""

    def __init__(self, config: AttrDict) -> None:
        """Initialize."""
        self._tvdb = tvdb_v4_official.TVDB(config.tvdb_api_key)
        # tvdb_v4_official stores pagination state on the shared Request
        # object; serialize HTTP calls to keep that state consistent.
        self._tvdb_lock: Lock = Lock()
        self._cache = LookupCache(config.cache_expiry_days)

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

    def _query_api(
        self, title: str, parsed: ParseResult
    ) -> tuple[dict | None, list[LogEvent]]:
        """
        Query TVDB API.

        Returns ``(result, events)`` where ``result`` is:
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
            return {}, [
                LogEvent("lookup_error", f"TVDB lookup failed for '{title}': {exc}")
            ]

        # TVDB doesn't raise on HTTP errors — it returns a dict with
        # ``code`` and ``message`` keys. Treat those as an error just like
        # TMDB's HTTPError path.
        if _is_tvdb_error_dict(result):
            assert isinstance(result, dict)
            code = result.get("code", 0)
            msg = result.get("message", "")
            label = parsed.tvdb_id or title or "(unknown)"
            if code == _RATE_LIMIT_STATUS:
                event = LogEvent(
                    "lookup_rate_limited",
                    f"TVDB rate limited for '{label}': {msg}",
                )
            else:
                event = LogEvent(
                    "lookup_error",
                    f"TVDB HTTP error {code} for '{label}': {msg}",
                )
            return {}, [event]

        return result, []

    def _lookup_by_id_language(self, parsed: ParseResult) -> LookupResult:
        """Look up language by TVDB ID, bypassing title-based caching."""
        events: list[LogEvent] = []
        if parsed.tvdb_id:
            found, cached_lang, cache_events = self._cache.check_id_cache(
                "tv", "tvdb", parsed.tvdb_id
            )
            events.extend(cache_events)
            if found:
                return LookupResult(lang=cached_lang, events=tuple(events))

        result, query_events = self._query_api("", parsed)
        events.extend(query_events)
        if result == {}:
            return LookupResult(lang=None, events=tuple(events))
        if not result:
            events.append(
                LogEvent(
                    "lookup_no_result",
                    f"TVDB ID {parsed.tvdb_id}: no result found",
                )
            )
            return LookupResult(lang=None, events=tuple(events))

        lang = self._resolve_language(result) or ""
        if parsed.tvdb_id:
            save_events = self._cache.save_id(
                "tv",
                "tvdb",
                parsed.tvdb_id,
                db_id=self._extract_db_id(result),
                language=lang,
            )
            events.extend(save_events)

        if lang:
            events.append(
                LogEvent(
                    "lookup_hit", f"TVDB ID {parsed.tvdb_id}: original language: {lang}"
                )
            )
        else:
            events.append(
                LogEvent(
                    "lookup_no_result", f"TVDB ID {parsed.tvdb_id}: no result found"
                )
            )
        return LookupResult(lang=lang or None, events=tuple(events))

    def _lookup_by_title_language(
        self, title: str, parsed: ParseResult
    ) -> LookupResult:
        """Look up language by title search with caching."""
        events: list[LogEvent] = []
        found, lang, cache_events = self._cache.check_cache("tv", title, "")
        events.extend(cache_events)
        if found:
            return LookupResult(lang=lang, events=tuple(events))

        result, query_events = self._query_api(title, parsed)
        events.extend(query_events)
        if result == {}:
            return LookupResult(lang=None, events=tuple(events))

        if result is not None:
            lang = self._resolve_language(result) or ""
            save_events = self._cache.save_file(
                "tv",
                title,
                "",
                db_id=self._extract_db_id(result),
                language=lang,
            )
            events.extend(save_events)
        else:
            save_events = self._cache.save_file("tv", title, "")
            events.extend(save_events)
            lang = ""

        self._cache.set_mem("tv", title, "", lang or None)
        if lang:
            events.append(
                LogEvent("lookup_hit", f"TVDB: '{title}' original language: {lang}")
            )
        else:
            events.append(
                LogEvent("lookup_no_result", f"TVDB: '{title}' no result found")
            )
        return LookupResult(lang=lang or None, events=tuple(events))

    def lookup_language(self, path: Path) -> LookupResult:
        """
        Look up the original language for a TV series file.

        Returns a :class:`LookupResult` with an ISO 639-3 language code (or
        ``None``) and a tuple of deferred log events for the main thread to
        replay.
        """
        parsed = parse_title(path.stem, "tv")

        if parsed.tvdb_id:
            return self._lookup_by_id_language(parsed)

        if not parsed.title:
            return LookupResult()

        return self._lookup_by_title_language(parsed.title, parsed)
