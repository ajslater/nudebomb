"""TMDB API lookup for media language detection."""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

import tmdbsimple as tmdb
from loguru import logger
from requests.exceptions import HTTPError

from nudebomb.log import LOOKUP_HIT_LEVEL
from nudebomb.log.reporter import Reporter
from nudebomb.lookup.cache import LookupCache
from nudebomb.lookup.parser import parse_title
from nudebomb.lookup.util import format_title_year, resolve_language

if TYPE_CHECKING:
    from pathlib import Path

    from confuse import AttrDict

    from nudebomb.lookup.parser import ParseResult

_RATE_LIMIT_STATUS: Final = 429


class TMDBLookup:
    """Look up original language of media from TMDB."""

    def __init__(self, config: AttrDict, reporter: Reporter | None = None) -> None:
        """Initialize."""
        tmdb.API_KEY = config.tmdb_api_key
        self._reporter: Reporter = reporter if reporter is not None else Reporter()
        self._cache = LookupCache(config.cache_expiry_days, self._reporter)
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

    def _query_api(self, title: str, year: str, parsed: ParseResult) -> dict | None:
        """
        Query TMDB API.

        Returns:
        - a dict on hit
        - ``None`` on no-result (cache as a miss)
        - ``{}`` on rate-limit or error (do not cache — retry next run)

        Side effects: emits warning/error log + progress mark + stats
        bookkeeping for rate-limits and errors.

        """
        try:
            if parsed.tmdb_id or parsed.imdb_id:
                return self._lookup_by_id(parsed)
            return self._search_tmdb(title, year)
        except HTTPError as exc:
            response = exc.response
            title_year = format_title_year(title, year)
            if response is not None and response.status_code == _RATE_LIMIT_STATUS:
                msg = f"TMDB rate limited for '{title_year}'"
                logger.warning(msg)
                self._reporter.progress.mark_lookup_rate_limited()
                self._reporter.stats.record_db_remote_error(msg)
            else:
                msg = f"TMDB HTTP error for '{title_year}': {exc}"
                logger.error(msg)
                self._reporter.progress.mark_lookup_error()
                self._reporter.stats.record_db_remote_error(msg)
            return {}
        except Exception as exc:
            title_year = format_title_year(title, year)
            msg = f"TMDB lookup failed for '{title_year}': {exc}"
            logger.error(msg)
            self._reporter.progress.mark_lookup_error()
            self._reporter.stats.record_db_remote_error(msg)
            return {}

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
        """Look up language by TMDB/IMDB ID, bypassing title-based caching."""
        found, cached_lang = self._check_id_caches(parsed)
        if found:
            return cached_lang

        result = self._query_api("", "", parsed)
        if result == {}:
            # Rate-limited or error: do not cache, retry next run.
            return None
        id_str = parsed.tmdb_id or parsed.imdb_id
        label = f"TMDB ID {id_str}"
        if not result:
            # Genuine no-result; IDs aren't cached as misses today.
            self._record_remote_no_result(label)
            return None

        lang = resolve_language(result) or ""
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

    def _lookup_by_title_language(
        self, title: str, year: str, parsed: ParseResult
    ) -> str | None:
        """Look up language by title search with caching."""
        cache_type = self._media_type
        found, lang = self._cache.check_cache(cache_type, title, year)
        if found:
            return lang

        # Query API
        result = self._query_api(title, year, parsed)
        if result == {}:
            # Rate-limited or error: do not cache.
            return None

        if result is not None:
            lang = resolve_language(result) or ""
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
