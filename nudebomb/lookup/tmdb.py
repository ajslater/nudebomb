"""TMDB API lookup for media language detection."""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

import tmdbsimple as tmdb
from loguru import logger
from requests.exceptions import HTTPError

from nudebomb.lookup.base import QUERY_ERROR, BaseLookup, QueryOutcome
from nudebomb.lookup.parser import parse_title
from nudebomb.lookup.util import (
    LOOKUP_TIMEOUT_SECONDS,
    best_title_match,
    format_title_year,
    redact_api_key,
    resolve_tmdb_language,
)

if TYPE_CHECKING:
    from pathlib import Path

    from nudebomb.config import NudebombSettings
    from nudebomb.log.reporter import Reporter
    from nudebomb.lookup.cache import LookupCache
    from nudebomb.lookup.parser import ParseResult

_RATE_LIMIT_STATUS: Final = 429


def _result_titles(result: dict) -> list[str]:
    """
    Every candidate name for a TMDB result.

    Includes the original-language title so a romanized query still
    matches media whose localized title differs from the original.
    """
    keys = ("title", "name", "original_title", "original_name")
    return [
        value for key in keys if isinstance(value := result.get(key), str) and value
    ]


def _result_year(result: dict) -> str:
    """Year field for a TMDB result."""
    date = result.get("release_date") or result.get("first_air_date") or ""
    return date[:4]


class TMDBLookup(BaseLookup):
    """Look up original language of media from TMDB."""

    def __init__(
        self,
        config: NudebombSettings,
        reporter: Reporter | None = None,
        cache: LookupCache | None = None,
    ) -> None:
        """Initialize."""
        # tmdbsimple holds its configuration as module globals by design.
        # No lock is needed around calls: API objects are constructed
        # fresh per request and REQUESTS_SESSION stays unset, so each
        # call uses its own requests.Session.
        tmdb.API_KEY = config.tmdb_api_key
        # tmdbsimple types this from its env-var default, but it goes
        # straight to requests, which wants a number.
        tmdb.REQUESTS_TIMEOUT = LOOKUP_TIMEOUT_SECONDS  # ty: ignore[invalid-assignment]
        super().__init__(config, reporter, cache)
        self._media_type: str = config.media_type or ""

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

        candidates = [r for r in results if r.get("media_type") in ("movie", "tv")]
        return best_title_match(candidates, title, year, _result_titles, _result_year)

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

    def _query_api(self, title: str, year: str, parsed: ParseResult) -> QueryOutcome:
        """
        Query TMDB API.

        Side effects: emits warning/error log + progress mark + stats
        bookkeeping for rate-limits and errors.
        """
        try:
            if parsed.tmdb_id or parsed.imdb_id:
                return QueryOutcome(result=self._lookup_by_id(parsed))
            return QueryOutcome(result=self._search_tmdb(title, year))
        except HTTPError as exc:
            response = exc.response
            title_year = format_title_year(title, year)
            if response is not None and response.status_code == _RATE_LIMIT_STATUS:
                msg = f"TMDB rate limited for '{title_year}'"
                logger.warning(msg)
                self._reporter.progress.mark_lookup_rate_limited()
                self._reporter.stats.record_db_remote_error(msg)
            else:
                # Redact: tmdbsimple sends the api_key as a URL query
                # parameter and requests embeds the full URL in
                # exception text.
                msg = f"TMDB HTTP error for '{title_year}': {redact_api_key(str(exc))}"
                logger.error(msg)
                self._reporter.progress.mark_lookup_error()
                self._reporter.stats.record_db_remote_error(msg)
            return QUERY_ERROR
        except Exception as exc:
            title_year = format_title_year(title, year)
            msg = f"TMDB lookup failed for '{title_year}': {redact_api_key(str(exc))}"
            logger.error(msg)
            self._reporter.progress.mark_lookup_error()
            self._reporter.stats.record_db_remote_error(msg)
            return QUERY_ERROR

    def _id_lookup_keys(self, parsed: ParseResult) -> list[tuple[str, str]]:
        """Return (id_type, id_value) pairs present on the parse result."""
        keys: list[tuple[str, str]] = []
        if parsed.tmdb_id:
            keys.append(("tmdb", parsed.tmdb_id))
        if parsed.imdb_id:
            keys.append(("imdb", parsed.imdb_id))
        return keys

    def _check_id_caches(self, parsed: ParseResult) -> tuple[bool, str | None]:
        """Check caches for any known ID across both media types."""
        for id_type, id_value in self._id_lookup_keys(parsed):
            for media_type in ("movie", "tv"):
                found, lang = self._cache.check_id_cache(media_type, id_type, id_value)
                if found:
                    return True, lang
        return False, None

    def _lookup_by_id_language(self, parsed: ParseResult) -> str | None:
        """Look up language by TMDB/IMDB ID, bypassing title-based caching."""
        found, cached_lang = self._check_id_caches(parsed)
        if found:
            return cached_lang

        outcome = self._query_api("", "", parsed)
        if outcome.error:
            # Rate-limited or error: do not cache, retry next run.
            return None
        result = outcome.result
        id_str = parsed.tmdb_id or parsed.imdb_id
        label = f"TMDB ID {id_str}"
        if not result:
            # Genuine no-result; IDs aren't cached as misses today.
            self._record_remote_no_result(label)
            return None

        lang = resolve_tmdb_language(result) or ""
        media_type = result.get("media_type", "")
        db_id = self._extract_db_id(result)
        if media_type:
            for id_type, id_value in self._id_lookup_keys(parsed):
                self._cache.save_id(
                    media_type, id_type, id_value, db_id=db_id, language=lang
                )

        if lang:
            self._record_remote_hit(label, lang)
        else:
            self._record_remote_no_result(label)
        return lang or None

    def _check_title_caches(self, title: str, year: str) -> tuple[bool, str | None]:
        """
        Check the title cache under every location a hit could live.

        Writes land under the result's media type (or the root when
        unknown), so with no configured media type a hit may live under
        any of the three locations.
        """
        cache_type = self._media_type
        check_types = (cache_type,) if cache_type else ("", "movie", "tv")
        for check_type in check_types:
            found, lang = self._cache.check_cache(check_type, title, year)
            if found:
                return True, lang
        return False, None

    def _lookup_by_title_language(
        self, title: str, year: str, parsed: ParseResult
    ) -> str | None:
        """Look up language by title search with caching."""
        cache_type = self._media_type
        found, lang = self._check_title_caches(title, year)
        if found:
            return lang

        # Query API
        outcome = self._query_api(title, year, parsed)
        if outcome.error:
            # Rate-limited or error: do not cache.
            return None

        result = outcome.result
        if result is not None:
            lang = resolve_tmdb_language(result) or ""
            result_media_type = result.get("media_type", "")
            self._cache.save_file(
                result_media_type or cache_type,
                title,
                year,
                db_id=self._extract_db_id(result),
                language=lang,
            )
        else:
            self._cache.save_file(cache_type, title, year)
            lang = ""

        self._cache.set_mem(cache_type, title, year, lang or None)
        label = f"TMDB: '{title}'"
        if lang:
            self._record_remote_hit(label, lang)
        else:
            self._record_remote_no_result(label)
        return lang or None

    def lookup_language(self, path: Path) -> str | None:
        """
        Look up the original language for a media file.

        Returns an ISO 639-3 language code (or ``None``). All log /
        progress / stats side effects happen inline.
        """
        parsed = parse_title(path.stem, self._media_type)

        if parsed.tmdb_id or parsed.imdb_id:
            return self._lookup_by_id_language(parsed)

        if not parsed.title:
            return None

        return self._lookup_by_title_language(parsed.title, parsed.year, parsed)
