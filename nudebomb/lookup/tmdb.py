"""TMDB API lookup for media language detection."""

from pathlib import Path
from typing import Final

import tmdbsimple as tmdb
from confuse import AttrDict
from requests.exceptions import HTTPError

from nudebomb.lookup.cache import LookupCache
from nudebomb.lookup.parser import ParseResult, parse_title
from nudebomb.lookup.util import (
    LogEvent,
    LookupResult,
    format_title_year,
    resolve_language,
)

_RATE_LIMIT_STATUS: Final = 429


class TMDBLookup:
    """Look up original language of media from TMDB."""

    def __init__(self, config: AttrDict) -> None:
        """Initialize."""
        tmdb.API_KEY = config.tmdb_api_key
        self._cache = LookupCache(config.cache_expiry_days)
        self._media_type: str = config.media_type

    def _search_tmdb(
        self, title: str, year: str = "", media_type: str = ""
    ) -> dict | None:
        """Search TMDB with specific parameters for better accuracy."""
        search = tmdb.Search()

        effective_type = media_type or self._media_type

        match effective_type:
            case "movie":
                search.movie(query=title, year=year)
            case "tv":
                search.tv(query=title, first_air_date_year=year)
            case _:
                query_str = f"{title} {year}" if year else title
                search.multi(query=query_str)

        results = search.results  # pyright: ignore[reportAttributeAccessIssue], # ty: ignore[unresolved-attribute]

        if effective_type:
            for r in results:
                r["media_type"] = effective_type

        if not results:
            return None

        for result in results:
            if result.get("media_type") in ("movie", "tv"):
                return result

        return None

    def _lookup_by_id(self, parsed: ParseResult) -> dict | None:
        """Look up a media item directly by TMDB or IMDB ID."""
        if parsed.tmdb_id:
            # Try movie first, then TV
            for get_fn, media_type in (
                (tmdb.Movies, "movie"),
                (tmdb.TV, "tv"),
            ):
                try:
                    result = get_fn(int(parsed.tmdb_id)).info()
                except HTTPError:
                    continue
                else:
                    result["media_type"] = media_type
                    return result
        if parsed.imdb_id:
            find = tmdb.Find(parsed.imdb_id)  # pyright: ignore[reportArgumentType]
            find.info(external_source="imdb_id")
            results = find.movie_results  # pyright: ignore[reportAttributeAccessIssue], # ty: ignore[unresolved-attribute]
            if results:
                results[0]["media_type"] = "movie"
                return results[0]
            results = find.tv_results  # pyright: ignore[reportAttributeAccessIssue], # ty: ignore[unresolved-attribute]
            if results:
                results[0]["media_type"] = "tv"
                return results[0]
        return None

    @staticmethod
    def _extract_db_id(result: dict) -> str:
        """Extract the database ID from a TMDB result."""
        return str(result.get("id", ""))

    def _query_api(
        self, title: str, year: str, parsed: ParseResult
    ) -> tuple[dict | None, list[LogEvent]]:
        """
        Query TMDB API.

        Returns ``(result, events)`` where ``result`` is:
        - a dict on hit
        - ``None`` on no-result (cache as a miss)
        - ``{}`` on rate-limit or error (do not cache — retry next run)
        """
        try:
            if parsed.tmdb_id or parsed.imdb_id:
                return self._lookup_by_id(parsed), []
            return self._search_tmdb(title, year), []
        except HTTPError as exc:
            response = exc.response
            title_year = format_title_year(title, year)
            if response is not None and response.status_code == _RATE_LIMIT_STATUS:
                event = LogEvent(
                    "lookup_rate_limited",
                    f"TMDB rate limited for '{title_year}'",
                )
            else:
                event = LogEvent(
                    "lookup_error",
                    f"TMDB HTTP error for '{title_year}': {exc}",
                )
            return {}, [event]
        except Exception as exc:
            title_year = format_title_year(title, year)
            return {}, [
                LogEvent(
                    "lookup_error",
                    f"TMDB lookup failed for '{title_year}': {exc}",
                )
            ]

    def _id_lookup_keys(self, parsed: ParseResult) -> list[tuple[str, str]]:
        """Return (id_type, id_value) pairs present on the parse result."""
        keys: list[tuple[str, str]] = []
        if parsed.tmdb_id:
            keys.append(("tmdb", parsed.tmdb_id))
        if parsed.imdb_id:
            keys.append(("imdb", parsed.imdb_id))
        return keys

    def _check_id_caches(
        self, parsed: ParseResult
    ) -> tuple[bool, str | None, list[LogEvent]]:
        """Check caches for any known ID across both media types."""
        events: list[LogEvent] = []
        for id_type, id_value in self._id_lookup_keys(parsed):
            for media_type in ("movie", "tv"):
                found, lang, check_events = self._cache.check_id_cache(
                    media_type, id_type, id_value
                )
                events.extend(check_events)
                if found:
                    return True, lang, events
        return False, None, events

    def _lookup_by_id_language(self, parsed: ParseResult) -> LookupResult:
        """Look up language by TMDB/IMDB ID, bypassing title-based caching."""
        events: list[LogEvent] = []
        found, cached_lang, cache_events = self._check_id_caches(parsed)
        events.extend(cache_events)
        if found:
            return LookupResult(lang=cached_lang, events=tuple(events))

        result, query_events = self._query_api("", "", parsed)
        events.extend(query_events)
        if result == {}:
            # Rate-limited or error: do not cache, retry next run.
            return LookupResult(lang=None, events=tuple(events))
        if not result:
            # Genuine no-result; IDs aren't cached as misses today.
            id_str = parsed.tmdb_id or parsed.imdb_id
            events.append(
                LogEvent("lookup_no_result", f"TMDB ID {id_str}: no result found")
            )
            return LookupResult(lang=None, events=tuple(events))

        lang = resolve_language(result) or ""
        media_type = result.get("media_type", "")
        db_id = self._extract_db_id(result)
        if media_type:
            for id_type, id_value in self._id_lookup_keys(parsed):
                save_events = self._cache.save_id(
                    media_type, id_type, id_value, db_id=db_id, language=lang
                )
                events.extend(save_events)

        id_str = parsed.tmdb_id or parsed.imdb_id
        if lang:
            events.append(
                LogEvent("lookup_hit", f"TMDB ID {id_str}: original language: {lang}")
            )
        else:
            events.append(
                LogEvent("lookup_no_result", f"TMDB ID {id_str}: no result found")
            )
        return LookupResult(lang=lang or None, events=tuple(events))

    def _lookup_by_title_language(
        self, title: str, year: str, parsed: ParseResult
    ) -> LookupResult:
        """Look up language by title search with caching."""
        cache_type = self._media_type
        events: list[LogEvent] = []

        found, lang, cache_events = self._cache.check_cache(cache_type, title, year)
        events.extend(cache_events)
        if found:
            return LookupResult(lang=lang, events=tuple(events))

        # Query API
        result, query_events = self._query_api(title, year, parsed)
        events.extend(query_events)
        if result == {}:
            # Rate-limited or error: do not cache.
            return LookupResult(lang=None, events=tuple(events))

        if result is not None:
            lang = resolve_language(result) or ""
            result_media_type = result.get("media_type", "")
            save_events = self._cache.save_file(
                result_media_type or cache_type,
                title,
                year,
                db_id=self._extract_db_id(result),
                language=lang,
            )
            events.extend(save_events)
        else:
            save_events = self._cache.save_file(cache_type, title, year)
            events.extend(save_events)
            lang = ""

        self._cache.set_mem(cache_type, title, year, lang or None)
        if lang:
            events.append(
                LogEvent("lookup_hit", f"TMDB: '{title}' original language: {lang}")
            )
        else:
            events.append(
                LogEvent("lookup_no_result", f"TMDB: '{title}' no result found")
            )
        return LookupResult(lang=lang or None, events=tuple(events))

    def lookup_language(self, path: Path) -> LookupResult:
        """
        Look up the original language for a media file.

        Returns a :class:`LookupResult` with an ISO 639-3 language code (or
        ``None``) and a tuple of deferred log events for the main thread to
        replay.
        """
        parsed = parse_title(path.stem, self._media_type)

        if parsed.tmdb_id or parsed.imdb_id:
            return self._lookup_by_id_language(parsed)

        if not parsed.title:
            return LookupResult()

        return self._lookup_by_title_language(parsed.title, parsed.year, parsed)
