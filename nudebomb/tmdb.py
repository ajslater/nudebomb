"""TMDB language lookup for media files."""

import json
import re
from pathlib import Path

import tmdbsimple as tmdb
from confuse import AttrDict

from nudebomb.langfiles import lang_to_alpha3
from nudebomb.printer import Printer
from nudebomb.version import PROGRAM_NAME

_TITLE_STOP_PATTERNS = re.compile(
    r"""
    (?:                     # non-capturing group for alternation
        [Ss]\d{1,2}[Ee]\d{1,2}  # S01E02
        | \d{3,4}[pPiI]    # 720p, 1080p, 1080i
        | (?<!\w)           # not preceded by a word char
          (?:19|20)\d{2}    # 4-digit year 1900-2099
          (?!\w)            # not followed by a word char
        | \b(?:REPACK|PROPER|RERIP|BluRay|BRRip|BDRip|WEBRip
              |WEB-DL|WEBDL|WEB|HDTV|DVDRip|HDRip|AMZN|NF|DSNP
              |HMAX|ATVP|PCOK|x264|x265|h264|h265|HEVC|AVC
              |AAC|AC3|DTS|FLAC|MULTI|REMUX|DDP|DD|Atmos
              |10bit|HDR|SDR|DoVi)\b
    )
    """,
    re.VERBOSE | re.IGNORECASE,
)

_SPACE_CHARS = re.compile(r"[._]")
_PARENS = re.compile(r"\(.*?\)|\[.*?\]")
_MULTI_SPACE = re.compile(r"\s{2,}")


def _parse_title(stem: str) -> str:
    """Extract a searchable title from an MKV filename stem."""
    # Remove bracketed/parenthesized groups (release groups, years, etc.)
    title = _PARENS.sub(" ", stem)
    # Replace dots and underscores with spaces
    title = _SPACE_CHARS.sub(" ", title)
    # Truncate at the first stop-pattern match
    if match := _TITLE_STOP_PATTERNS.search(title):
        title = title[: match.start()]
    # Collapse whitespace and strip
    return _MULTI_SPACE.sub(" ", title).strip(" -")


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
        self._mem_cache: dict[str, str | None] = {}
        # File cache directory
        config_dir = Path.home() / f".config/{PROGRAM_NAME}"
        self._cache_dir: Path = config_dir / "tmdb_cache"
        self._cache_dir.mkdir(parents=True, exist_ok=True)

    def _cache_path(self, title: str) -> Path:
        """Return the cache file path for a title."""
        return self._cache_dir / f"{_sanitize_cache_key(title)}.json"

    def _load_cached(self, title: str) -> dict | None:
        """Load cached TMDB response for a title."""
        path = self._cache_path(title)
        if path.is_file():
            try:
                with path.open("r") as f:
                    return json.load(f)
            except (json.JSONDecodeError, OSError):
                pass
        return None

    def _save_cache(self, title: str, data: dict) -> None:
        """Save a TMDB response to the file cache."""
        path = self._cache_path(title)
        try:
            with path.open("w") as f:
                json.dump(data, f, indent=2)
        except OSError as exc:
            self._printer.warn(f"Could not write TMDB cache: {exc}")

    def _search_tmdb(self, title: str) -> dict | None:
        """Search TMDB for a title and return the first result."""
        try:
            search = tmdb.Search()
            search.multi(query=title)
            results = search.results
            if not results:
                return None
            # Filter to movie and tv results only
            for result in results:
                if result.get("media_type") in ("movie", "tv"):
                    return result
        except Exception as exc:
            self._printer.warn(f"TMDB lookup failed for '{title}': {exc}")
        return None

    def lookup_language(self, path: Path) -> str | None:
        """
        Look up the original language for a media file.

        Returns an ISO 639-3 language code or None.
        """
        title = _parse_title(path.stem)
        if not title:
            return None

        # Check in-memory cache first
        if title in self._mem_cache:
            return self._mem_cache[title]

        # Check file cache
        result = self._load_cached(title)
        if result is None:
            # Query TMDB
            self._printer.extra_info(f"\tTMDB lookup: '{title}'")
            result = self._search_tmdb(title)
            if result is not None:
                self._save_cache(title, result)
            else:
                # Cache the miss as an empty dict so we don't re-query
                self._save_cache(title, {})

        lang_2 = result.get("original_language") if result else None
        if lang_2:
            lang_3 = lang_to_alpha3(lang_2)
            self._printer.config(f"TMDB: '{title}' original language: {lang_3}")
            self._mem_cache[title] = lang_3
            return lang_3

        self._mem_cache[title] = None
        return None
