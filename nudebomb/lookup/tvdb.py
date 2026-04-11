"""TVDB API lookup for TV series language detection."""

from pathlib import Path

import tvdb_v4_official
from confuse import AttrDict

from nudebomb.langfiles import lang_to_alpha3
from nudebomb.lookup.cache import LookupCache
from nudebomb.lookup.parser import ParseResult, parse_title
from nudebomb.printer import Printer


class TVDBLookup:
    """Look up original language of TV series from TVDB."""

    def __init__(self, config: AttrDict) -> None:
        """Initialize."""
        self._printer: Printer = Printer(config.verbose)
        self._tvdb = tvdb_v4_official.TVDB(config.tvdb_api_key)
        self._cache = LookupCache(self._printer, config.cache_expiry_days)

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
        results = self._tvdb.search(title, type="series")
        if not results:
            return None
        return results[0]

    def _lookup_by_id(self, tvdb_id: str) -> dict | None:
        """Look up a TV series directly by TVDB ID."""
        result = self._tvdb.get_series(int(tvdb_id))
        if not result:
            return None
        return result

    @staticmethod
    def _extract_db_id(result: dict) -> str:
        """Extract the database ID from a TVDB result."""
        return str(result.get("id", ""))

    def _query_api(self, title: str, parsed: ParseResult) -> dict | None:
        """Query TVDB API, returning raw result or empty dict on error."""
        try:
            if parsed.tvdb_id:
                return self._lookup_by_id(parsed.tvdb_id)
            return self._search_tvdb(title)
        except Exception as exc:
            self._printer.lookup_error(f"TVDB lookup failed for '{title}': {exc}")
            return {}

    def _lookup_by_id_language(self, parsed: ParseResult) -> str | None:
        """Look up language by TVDB ID, bypassing title-based caching."""
        result = self._query_api("", parsed)
        if not result:
            return None

        lang = self._resolve_language(result) or ""
        if parsed.title:
            self._cache.save_file(
                "tv",
                parsed.title,
                "",
                db_id=self._extract_db_id(result),
                language=lang,
            )
            self._cache.set_mem("tv", parsed.title, "", lang or None)

        if lang:
            self._printer.lookup_hit(
                f"TVDB ID {parsed.tvdb_id}: original language: {lang}"
            )
        else:
            self._printer.lookup_no_result(f"TVDB ID {parsed.tvdb_id}: no result found")
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
        if lang:
            self._printer.lookup_hit(f"TVDB: '{title}' original language: {lang}")
        else:
            self._printer.lookup_no_result(f"TVDB: '{title}' no result found")
        return lang or None

    def lookup_language(self, path: Path) -> str | None:
        """
        Look up the original language for a TV series file.

        Returns an ISO 639-3 language code or None.
        """
        parsed = parse_title(path.stem, "tv")

        if parsed.tvdb_id:
            return self._lookup_by_id_language(parsed)

        if not parsed.title:
            return ""

        return self._lookup_by_title_language(parsed.title, parsed)
