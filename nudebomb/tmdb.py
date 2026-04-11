"""TMDB language lookup for media files."""

import json
import re
from pathlib import Path
from typing import Final

import tmdbsimple as tmdb
from confuse import AttrDict
from requests.exceptions import HTTPError

from nudebomb.langfiles import lang_to_alpha3
from nudebomb.printer import Printer
from nudebomb.version import PROGRAM_NAME

# Looks for a 4-digit year (1900-2099)
_YEAR_PATTERN: Final = re.compile(r"\b((?:19|20)\d{2})\b")

_IGNORE_PATTERN: Final = re.compile(
    r"-(?:behindthescenes|deleted|featurette|interview|scene|short|trailer|other)$",
    re.IGNORECASE,
)
# General noise markers to truncate the title if no year is found
_NOISE_CUTOFF: Final = re.compile(
    r"""(?ix)
    \b(s\d+e\d+|\d+x\d+|480p|720p|1080p|2160p|4k|uhd|hdtv|bluray|web-?dl|remux|x264|h264|x265|hevc)\b|[\[\(\{]
    """,
    re.IGNORECASE,
)

_DELIMITERS: Final = re.compile(r"[._\s]+")
_CLEAN_TRIM: Final = re.compile(r"^\s*[-–—\s]+|\s*[-–—\s]+$")  # noqa: RUF001
_RATE_LIMIT_STATUS: Final = 429


def parse_title(filename: str) -> tuple[str, str]:
    """Parse title and year from filename."""
    # 1. Strip extension and normalize delimiters to spaces
    stem = filename.rsplit(".", 1)[0]
    normalized = _DELIMITERS.sub(" ", stem).strip()

    if _IGNORE_PATTERN.search(normalized):
        return ("", "")

    title = normalized
    year = ""

    # 2. Try to find the year
    year_match = _YEAR_PATTERN.search(normalized)

    # 3. Logic: If year exists, it's our primary anchor.
    # Otherwise, look for the first piece of "scene noise".
    if year_match:
        year = year_match.group(1)
        # Title is everything before the year
        title = normalized[: year_match.start()]
    else:
        noise_match = _NOISE_CUTOFF.search(normalized)
        if noise_match:
            title = normalized[: noise_match.start()]

    # 4. Final Polish
    clean_title = _CLEAN_TRIM.sub("", title).strip()
    return (clean_title, year)


def _sanitize_cache_key(title: str) -> str:
    """Create a filesystem-safe cache key from a title."""
    key = title.lower().strip()
    key = re.sub(r"[^\w\s-]", "", key)
    return re.sub(r"\s+", "_", key)


class TMDBLookup:
    """Look up original language of media from TMDB."""

    def __init__(self, config: AttrDict) -> None:
        """Initialize."""
        self._printer: Printer = Printer(config.verbose)
        tmdb.API_KEY = config.tmdb_api_key
        # In-memory cache: parsed_title -> alpha3 language or None
        self._mem_cache: dict[tuple[str, str], str | None] = {}
        # File cache directory
        config_dir = Path.home() / f".config/{PROGRAM_NAME}"
        self._cache_dir: Path = config_dir / "tmdb_cache"
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._media_type: str = config.media_type

    def _cache_path(self, title: str, year: str) -> Path:
        """Return the cache file path for a title."""
        year_str = f"({year})" if year else ""
        return self._cache_dir / f"{_sanitize_cache_key(title)}{year_str}.json"

    def _load_cached(self, title: str, year: str) -> dict | None:
        """Load cached TMDB response for a title."""
        path = self._cache_path(title, year)
        if path.is_file():
            try:
                with path.open("r") as f:
                    return json.load(f)
            except (json.JSONDecodeError, OSError):
                pass
        return None

    def _save_cache(self, title: str, year: str, data: dict) -> None:
        """Save a TMDB response to the file cache."""
        path = self._cache_path(title, year)
        try:
            with path.open("w") as f:
                json.dump(data, f, indent=2)
        except OSError as exc:
            self._printer.warn(f"Could not write TMDB cache: {exc}")

    def _search_tmdb(self, title: str, year: str = "") -> dict | None:
        """Search TMDB with specific parameters for better accuracy."""
        search = tmdb.Search()

        match self._media_type:
            case "movie":
                search.movie(query=title, year=year)
            case "tv":
                search.tv(query=title, first_air_date_year=year)
            case _:
                # If media_type is unknown, we fold the year into the query string
                query_str = f"{title} {year}" if year else title
                search.multi(query=query_str)

        results = search.results  # pyright: ignore[reportAttributeAccessIssue], # ty: ignore[unresolved-attribute]

        if self._media_type:
            # TV & Movie results don't include 'media_type', so we inject it for consistency
            for r in results:
                r["media_type"] = self._media_type

        if not results:
            return None

        # Return the first valid movie or tv result
        for result in results:
            if result.get("media_type") in ("movie", "tv"):
                return result

        return None

    @staticmethod
    def _resolve_language(result: dict) -> str | None:
        """Extract and convert language from a TMDB result."""
        lang_2 = result.get("original_language")
        if not lang_2:
            return None
        return lang_to_alpha3(lang_2)

    def _lookup_language_check_mem_cache(self, title: str, year: str) -> str | None:
        """Check in-memory cache first."""
        lang: str | None = None
        key = (title, year)
        if key in self._mem_cache:
            title_str = f"{title} ({year})" if year else title
            if lang := self._mem_cache.get(key, ""):
                self._printer.tmdb_cache_hit(
                    f"TMDB mem cache: '{title_str}' original language: {lang}"
                )
            else:
                self._printer.tmdb_no_result(
                    f"TMDB mem cache: '{title_str}' no language found"
                )
        return lang

    def _lookup_language_check_file_cache(self, title: str, year: str) -> str | None:
        """Check file cache."""
        lang = None
        cached = self._load_cached(title, year)
        if cached is not None:
            lang = self._resolve_language(cached)
            self._mem_cache[(title, year)] = lang
            title_str = f"{title} ({year})" if year else title
            if lang:
                self._printer.tmdb_cache_hit(
                    f"TMDB file cache: '{title_str}' original language: {lang}"
                )
            else:
                self._printer.tmdb_no_result(
                    f"TMDB file cache: '{title_str}' no language found"
                )
            return lang
        return lang

    def _lookup_language_tmdb_api(self, title: str, year: str) -> dict | None:
        """Query TMDB API."""
        title_str = f"{title} ({year})" if year else title
        try:
            result = self._search_tmdb(title, year)
        except HTTPError as exc:
            response = exc.response
            if response is not None and response.status_code == _RATE_LIMIT_STATUS:
                self._printer.tmdb_rate_limited(f"TMDB rate limited for '{title_str}'")
            else:
                self._printer.tmdb_error(f"TMDB HTTP error for '{title_str}': {exc}")
            result = {}
        except Exception as exc:
            self._printer.tmdb_error(f"TMDB lookup failed for '{title_str}': {exc}")
            result = {}
        return result

    def lookup_language(self, path: Path) -> str | None:
        """
        Look up the original language for a media file.

        Returns an ISO 639-3 language code or None.
        """
        title, year = parse_title(path.stem)
        if not title:
            return ""

        if lang := self._lookup_language_check_mem_cache(title, year):
            return lang

        if lang := self._lookup_language_check_file_cache(title, year):
            return lang

        result = self._lookup_language_tmdb_api(title, year)
        if result == {}:
            return None

        if result is not None:
            self._save_cache(title, year, result)
            lang = self._resolve_language(result)
        else:
            # Cache the miss so we don't re-query
            self._save_cache(title, year, {})
            lang = None

        self._mem_cache[(title, year)] = lang
        if lang:
            self._printer.tmdb_hit(f"TMDB: '{title}' original language: {lang}")
        else:
            self._printer.tmdb_no_result(f"TMDB: '{title}' no result found")
        return lang
