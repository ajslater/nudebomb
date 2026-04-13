"""Lookup caching with movie/tv separation and expiry for misses."""

import json
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Final

from platformdirs import user_cache_dir

from nudebomb.lookup.util import format_title_year
from nudebomb.printer import Printer
from nudebomb.version import PROGRAM_NAME

_MEDIA_TYPES: Final = frozenset({"movie", "tv"})
_SECONDS_PER_DAY: Final = 86400


def _sanitize_cache_key(title: str) -> str:
    """Create a filesystem-safe cache key from a title."""
    key = title.lower().strip()
    key = re.sub(r"[^\w\s-]", "", key)
    return re.sub(r"\s+", "_", key)


@dataclass(slots=True)
class CacheEntry:
    """A slim cache entry storing only the fields nudebomb uses."""

    cached_at: float = field(default_factory=time.time)
    db_id: str = ""
    language: str = ""
    title: str = ""
    year: str = ""

    def is_expired(self, expiry_days: int) -> bool:
        """
        Return True if this entry has expired.

        Only entries with no language found can expire.
        """
        if self.language:
            return False
        age = time.time() - self.cached_at
        return age > expiry_days * _SECONDS_PER_DAY


class LookupCache:
    """File and memory cache for lookups, separated by media type."""

    def __init__(self, printer: Printer, cache_expiry_days: int = 30) -> None:
        """Initialize."""
        self._printer = printer
        self._cache_expiry_days = cache_expiry_days
        # In-memory cache: (media_type, title, year) -> alpha3 language or None
        self._mem_cache: dict[tuple[str, str, str], str | None] = {}
        # File cache root
        self._cache_root: Path = Path(user_cache_dir(PROGRAM_NAME), ensure_exists=True)
        for media_type in _MEDIA_TYPES:
            (self._cache_root / media_type).mkdir(parents=True, exist_ok=True)

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

    def _load_entry(self, media_type: str, title: str, year: str) -> CacheEntry | None:
        """Load a cache entry from disk, returning None if missing or expired."""
        path = self._cache_path(media_type, title, year)
        if not path.is_file():
            return None
        try:
            data = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            return None

        entry = CacheEntry(**data)
        if entry.is_expired(self._cache_expiry_days):
            path.unlink(missing_ok=True)
            return None
        return entry

    def save_file(
        self,
        media_type: str,
        title: str,
        year: str,
        *,
        db_id: str = "",
        language: str = "",
    ) -> None:
        """Save a slim cache entry to the file cache."""
        entry = CacheEntry(
            db_id=db_id,
            language=language,
            title=title,
            year=year,
        )
        path = self._cache_path(media_type, title, year)
        try:
            path.write_text(json.dumps(asdict(entry), indent=2))
        except OSError as exc:
            self._printer.warn(f"Could not write cache: {exc}")

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
        title_year = format_title_year(title, year)
        if lang:
            self._printer.lookup_cache_hit(
                f"Mem cache: '{title_year}' original language: {lang}"
            )
        else:
            self._printer.lookup_no_result(
                f"Mem cache: '{title_year}' no language found"
            )
        return True, lang

    def _check_file_cache(
        self, media_type: str, title: str, year: str
    ) -> tuple[bool, str | None]:
        """Check file cache. Returns (found, lang)."""
        entry = self._load_entry(media_type, title, year)
        if entry is None:
            return False, None
        lang = entry.language or None
        self.set_mem(media_type, title, year, lang)
        title_year = format_title_year(title, year)
        if lang:
            self._printer.lookup_cache_hit(
                f"File cache: '{title_year}' original language: {lang}"
            )
        else:
            self._printer.lookup_no_result(
                f"File cache: '{title_year}' no language found"
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
