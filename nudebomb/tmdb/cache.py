"""TMDB caching with movie/tv separation."""

import json
import re
from pathlib import Path
from typing import Final

from nudebomb.printer import Printer
from nudebomb.tmdb.util import resolve_language, title_str
from nudebomb.version import PROGRAM_NAME

_MEDIA_TYPES: Final = frozenset({"movie", "tv"})


def _sanitize_cache_key(title: str) -> str:
    """Create a filesystem-safe cache key from a title."""
    key = title.lower().strip()
    key = re.sub(r"[^\w\s-]", "", key)
    return re.sub(r"\s+", "_", key)


class TMDBCache:
    """File and memory cache for TMDB lookups, separated by media type."""

    def __init__(self, printer: Printer) -> None:
        """Initialize."""
        self._printer = printer
        # In-memory cache: (media_type, title, year) -> alpha3 language or None
        self._mem_cache: dict[tuple[str, str, str], str | None] = {}
        # File cache root
        config_dir = Path.home() / f".config/{PROGRAM_NAME}"
        self._cache_root: Path = config_dir / "tmdb_cache"
        for media_type in _MEDIA_TYPES:
            (self._cache_root / media_type).mkdir(parents=True, exist_ok=True)
        # Keep the root for untyped lookups
        self._cache_root.mkdir(parents=True, exist_ok=True)

    def _cache_dir(self, media_type: str) -> Path:
        """Return the cache directory for a given media type."""
        if media_type in _MEDIA_TYPES:
            return self._cache_root / media_type
        return self._cache_root

    def _cache_path(self, media_type: str, title: str, year: str) -> Path:
        """Return the cache file path for a title."""
        year_str = f"({year})" if year else ""
        return (
            self._cache_dir(media_type) / f"{_sanitize_cache_key(title)}{year_str}.json"
        )

    def load_file(self, media_type: str, title: str, year: str) -> dict | None:
        """Load cached TMDB response for a title."""
        path = self._cache_path(media_type, title, year)
        if path.is_file():
            try:
                with path.open("r") as f:
                    return json.load(f)
            except (json.JSONDecodeError, OSError):
                pass
        return None

    def save_file(self, media_type: str, title: str, year: str, data: dict) -> None:
        """Save a TMDB response to the file cache."""
        path = self._cache_path(media_type, title, year)
        try:
            with path.open("w") as f:
                json.dump(data, f, indent=2)
        except OSError as exc:
            self._printer.warn(f"Could not write TMDB cache: {exc}")

    def get_mem(
        self, media_type: str, title: str, year: str
    ) -> tuple[bool, str | None]:
        """Check memory cache. Returns (found, lang)."""
        key = (media_type, title, year)
        if key in self._mem_cache:
            return True, self._mem_cache[key]
        return False, None

    def set_mem(self, media_type: str, title: str, year: str, lang: str | None) -> None:
        """Set a value in the memory cache."""
        self._mem_cache[(media_type, title, year)] = lang

    def _check_mem_cache(
        self, media_type: str, title: str, year: str
    ) -> tuple[bool, str | None]:
        """Check in-memory cache. Returns (found, lang)."""
        found, lang = self.get_mem(media_type, title, year)
        if not found:
            return False, None
        title_string = title_str(title, year)
        if lang:
            self._printer.tmdb_cache_hit(
                f"TMDB mem cache: '{title_string}' original language: {lang}"
            )
        else:
            self._printer.tmdb_no_result(
                f"TMDB mem cache: '{title_string}' no language found"
            )
        return True, lang

    def _check_file_cache(
        self, media_type: str, title: str, year: str
    ) -> tuple[bool, str | None]:
        """Check file cache. Returns (found, lang)."""
        cached = self.load_file(media_type, title, year)
        if cached is None:
            return False, None
        lang = resolve_language(cached)
        self.set_mem(media_type, title, year, lang)
        title_string = title_str(title, year)
        if lang:
            self._printer.tmdb_cache_hit(
                f"TMDB file cache: '{title_string}' original language: {lang}"
            )
        else:
            self._printer.tmdb_no_result(
                f"TMDB file cache: '{title_string}' no language found"
            )
        return True, lang

    def check_cache(
        self, cache_type: str, title: str, year: str
    ) -> tuple[bool, str | None]:
        """Check Caches."""
        found, lang = self._check_mem_cache(cache_type, title, year)
        if found:
            return found, lang
        found, lang = self._check_file_cache(cache_type, title, year)
        if found:
            return found, lang
        return False, lang
