"""TMDB API lookup for media language detection."""

from pathlib import Path
from typing import Final

import tmdbsimple as tmdb
from confuse import AttrDict
from requests.exceptions import HTTPError

from nudebomb.lookup.cache import LookupCache
from nudebomb.lookup.parser import ParseResult, parse_title
from nudebomb.lookup.util import resolve_language, title_str
from nudebomb.printer import Printer

_RATE_LIMIT_STATUS: Final = 429


class TMDBLookup:
    """Look up original language of media from TMDB."""

    def __init__(self, config: AttrDict) -> None:
        """Initialize."""
        self._printer: Printer = Printer(config.verbose)
        tmdb.API_KEY = config.tmdb_api_key
        self._cache = LookupCache(self._printer)
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

    def _query_api(self, title: str, year: str, parsed: ParseResult) -> dict | None:
        """Query TMDB API, returning raw result or empty dict on error."""
        try:
            if parsed.tmdb_id or parsed.imdb_id:
                return self._lookup_by_id(parsed)
            return self._search_tmdb(title, year)
        except HTTPError as exc:
            response = exc.response
            title_string = title_str(title, year)
            if response is not None and response.status_code == _RATE_LIMIT_STATUS:
                self._printer.lookup_rate_limited(
                    f"TMDB rate limited for '{title_string}'"
                )
            else:
                self._printer.lookup_error(
                    f"TMDB HTTP error for '{title_string}': {exc}"
                )
            return {}
        except Exception as exc:
            title_string = title_str(title, year)
            self._printer.lookup_error(
                f"TMDB lookup failed for '{title_string}': {exc}"
            )
            return {}

    def _lookup_by_id_language(self, parsed: ParseResult) -> str | None:
        """Look up language by TMDB/IMDB ID, bypassing title-based caching."""
        result = self._query_api("", "", parsed)
        if not result:
            return None

        lang = resolve_language(result)
        media_type = result.get("media_type", "")
        if parsed.title:
            self._cache.save_file(media_type, parsed.title, parsed.year, result)
            self._cache.set_mem(media_type, parsed.title, parsed.year, lang)

        id_str = parsed.tmdb_id or parsed.imdb_id
        if lang:
            self._printer.lookup_hit(f"TMDB ID {id_str}: original language: {lang}")
        else:
            self._printer.lookup_no_result(f"TMDB ID {id_str}: no result found")
        return lang

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
            return None

        if result is not None:
            result_media_type = result.get("media_type", "")
            self._cache.save_file(result_media_type or cache_type, title, year, result)
            lang = resolve_language(result)
        else:
            self._cache.save_file(cache_type, title, year, {})
            lang = None

        self._cache.set_mem(cache_type, title, year, lang)
        if lang:
            self._printer.lookup_hit(f"TMDB: '{title}' original language: {lang}")
        else:
            self._printer.lookup_no_result(f"TMDB: '{title}' no result found")
        return lang

    def lookup_language(self, path: Path) -> str | None:
        """
        Look up the original language for a media file.

        Returns an ISO 639-3 language code or None.
        """
        parsed = parse_title(path.stem, self._media_type)

        if parsed.tmdb_id or parsed.imdb_id:
            return self._lookup_by_id_language(parsed)

        if not parsed.title:
            return ""

        return self._lookup_by_title_language(parsed.title, parsed.year, parsed)
