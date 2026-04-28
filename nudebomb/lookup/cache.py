"""Lookup caching with movie/tv separation and expiry for misses."""

from __future__ import annotations

import json
import re
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from threading import Lock
from typing import Final

from loguru import logger
from platformdirs import user_cache_dir

from nudebomb.lookup.util import format_title_year
from nudebomb.reporter import Reporter
from nudebomb.version import PROGRAM_NAME

_MEDIA_TYPES: Final = frozenset({"movie", "tv"})
_SECONDS_PER_DAY: Final = 86400
_IDS_SUBDIR: Final = "ids"


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


def _atomic_write_text(path: Path, content: str) -> None:
    """
    Write ``content`` to ``path`` via a tmp file + rename.

    Each write is all-or-nothing — readers never see a half-written file.
    A uuid4 suffix keeps concurrent writers to the same target from
    clobbering each other's tmp files; the final ``replace`` is atomic so
    last-writer-wins is the worst case.
    """
    tmp_path = path.with_suffix(f"{path.suffix}.{uuid.uuid4().hex}.tmp")
    try:
        tmp_path.write_text(content)
        tmp_path.replace(path)
    except OSError:
        tmp_path.unlink(missing_ok=True)
        raise


class LookupCache:
    """
    File and memory cache for lookups, separated by media type.

    Thread-safe: a single lock guards all in-memory cache mutations. File
    writes go through :func:`_atomic_write_text` so readers never see a
    torn JSON file.
    """

    def __init__(
        self, cache_expiry_days: int = 30, reporter: Reporter | None = None
    ) -> None:
        """Initialize."""
        self._cache_expiry_days = cache_expiry_days
        self._reporter: Reporter = reporter if reporter is not None else Reporter()
        # In-memory cache: (media_type, title, year) -> alpha3 language or None
        self._mem_cache: dict[tuple[str, str, str], str | None] = {}
        # In-memory cache: (media_type, id_type, id_value) -> alpha3 language or None
        self._id_mem_cache: dict[tuple[str, str, str], str | None] = {}
        self._lock: Lock = Lock()
        # File cache root
        self._cache_root: Path = Path(user_cache_dir(PROGRAM_NAME))
        for media_type in _MEDIA_TYPES:
            (self._cache_root / media_type / _IDS_SUBDIR).mkdir(
                parents=True, exist_ok=True
            )

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
            _atomic_write_text(path, json.dumps(asdict(entry), indent=2))
        except OSError as exc:
            logger.warning(f"Could not write cache: {exc}")

    def get_mem(
        self, media_type: str, title: str, year: str
    ) -> tuple[bool, str | None]:
        """Check memory cache. Returns (found, lang)."""
        key = (media_type, title, year)
        with self._lock:
            if key in self._mem_cache:
                return True, self._mem_cache[key]
        return False, None

    def set_mem(self, media_type: str, title: str, year: str, lang: str | None) -> None:
        """Set a value in the memory cache."""
        with self._lock:
            self._mem_cache[(media_type, title, year)] = lang

    def _record_cache_hit(self, label: str, lang: str | None, source: str) -> None:
        """Record a cache hit; surface no-language hits in the no-results list."""
        self._reporter.stats.record_db_cache_hit()
        if lang:
            logger.debug(f"{source}: '{label}' original language: {lang}")
        else:
            logger.debug(f"{source}: '{label}' no language found")
            self._reporter.stats.record_db_no_result(f"{source}: '{label}'")

    def _check_mem_cache(
        self, media_type: str, title: str, year: str
    ) -> tuple[bool, str | None]:
        """Check in-memory cache. Returns (found, lang)."""
        found, lang = self.get_mem(media_type, title, year)
        if not found:
            return False, None
        self._record_cache_hit(format_title_year(title, year), lang, "Mem cache")
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
        self._record_cache_hit(format_title_year(title, year), lang, "File cache")
        return True, lang

    def check_cache(
        self, cache_type: str, title: str, year: str
    ) -> tuple[bool, str | None]:
        """Check Caches."""
        found, lang = self._check_mem_cache(cache_type, title, year)
        if found:
            return found, lang
        return self._check_file_cache(cache_type, title, year)

    def _id_cache_path(self, media_type: str, id_type: str, id_value: str) -> Path:
        """Return the cache file path for an ID entry."""
        return self._cache_dir(media_type) / _IDS_SUBDIR / f"{id_type}-{id_value}.json"

    def _load_id_entry(
        self, media_type: str, id_type: str, id_value: str
    ) -> CacheEntry | None:
        """Load an ID cache entry from disk, returning None if missing or expired."""
        path = self._id_cache_path(media_type, id_type, id_value)
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

    def save_id(
        self,
        media_type: str,
        id_type: str,
        id_value: str,
        *,
        db_id: str = "",
        language: str = "",
        title: str = "",
        year: str = "",
    ) -> None:
        """Save an ID-based entry to both memory and file caches."""
        with self._lock:
            self._id_mem_cache[(media_type, id_type, id_value)] = language or None
        entry = CacheEntry(
            db_id=db_id,
            language=language,
            title=title,
            year=year,
        )
        path = self._id_cache_path(media_type, id_type, id_value)
        try:
            _atomic_write_text(path, json.dumps(asdict(entry), indent=2))
        except OSError as exc:
            logger.warning(f"Could not write cache: {exc}")

    def _check_id_mem_cache(
        self, media_type: str, id_type: str, id_value: str
    ) -> tuple[bool, str | None]:
        """Check in-memory ID cache. Returns (found, lang)."""
        key = (media_type, id_type, id_value)
        with self._lock:
            if key not in self._id_mem_cache:
                return False, None
            lang = self._id_mem_cache[key]
        self._record_cache_hit(f"{id_type}-{id_value}", lang, "Mem cache")
        return True, lang

    def _check_id_file_cache(
        self, media_type: str, id_type: str, id_value: str
    ) -> tuple[bool, str | None]:
        """Check file ID cache. Returns (found, lang)."""
        entry = self._load_id_entry(media_type, id_type, id_value)
        if entry is None:
            return False, None
        lang = entry.language or None
        with self._lock:
            self._id_mem_cache[(media_type, id_type, id_value)] = lang
        self._record_cache_hit(f"{id_type}-{id_value}", lang, "File cache")
        return True, lang

    def check_id_cache(
        self, media_type: str, id_type: str, id_value: str
    ) -> tuple[bool, str | None]:
        """Check ID caches for a given media type."""
        found, lang = self._check_id_mem_cache(media_type, id_type, id_value)
        if found:
            return found, lang
        return self._check_id_file_cache(media_type, id_type, id_value)
