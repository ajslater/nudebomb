"""Tests for the lookup cache: thread-safety, expiry, corruption, persistence."""

import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Final
from unittest.mock import patch

import pytest

from nudebomb.log import setup as setup_logging
from nudebomb.log.reporter import Reporter
from nudebomb.log.summary import Stats
from nudebomb.lookup.cache import CacheEntry, LookupCache
from nudebomb.lookup.parser import ParseResult
from nudebomb.lookup.tmdb import TMDBLookup

__all__ = ()

_N_THREADS: Final = 8
_N_ITERATIONS: Final = 200


class TestLookupCacheThreadSafety:
    """The in-memory cache must survive concurrent readers and writers."""

    def test_concurrent_check_and_set(self, tmp_cache: LookupCache) -> None:
        """Hammer check_cache/set_mem from many threads; no crash, no loss."""

        def worker(i: int) -> tuple[bool, str | None]:
            title = f"title-{i % 16}"
            tmp_cache.set_mem("movie", title, "2024", f"eng-{i}")
            found, lang = tmp_cache.check_cache("movie", title, "2024")
            return found, lang

        with ThreadPoolExecutor(max_workers=_N_THREADS) as pool:
            results = list(pool.map(worker, range(_N_ITERATIONS)))

        # Every call must have returned a found entry (no None-language
        # leaks from a partial write).
        assert all(found for found, _ in results)
        assert all(lang is not None for _, lang in results)

    def test_concurrent_save_id(self, tmp_cache: LookupCache) -> None:
        """Concurrent save_id writes should not crash or tear files."""

        def worker(i: int) -> None:
            tmp_cache.save_id(
                "movie",
                "tmdb",
                str(i % 4),
                db_id=str(i),
                language="eng",
            )

        with ThreadPoolExecutor(max_workers=_N_THREADS) as pool:
            list(pool.map(worker, range(_N_ITERATIONS)))

        # File exists and parses back as valid JSON.
        for i in range(4):
            found, lang = tmp_cache.check_id_cache("movie", "tmdb", str(i))
            assert found
            assert lang == "eng"


class TestLookupCacheStats:
    """Cache hits update the Reporter's Stats counters."""

    def test_mem_hit_records_db_cache_hit(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "nudebomb.lookup.cache.user_cache_dir",
            lambda _prog: str(tmp_path),
        )
        reporter = Reporter(stats=Stats())
        cache = LookupCache(cache_expiry_days=30, reporter=reporter)
        cache.set_mem("tv", "Foo", "", "eng")

        found, lang = cache.check_cache("tv", "Foo", "")

        assert found
        assert lang == "eng"
        assert reporter.stats.db_cache_hits == 1
        assert reporter.stats.db_no_results == []

    def test_mem_miss_records_nothing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "nudebomb.lookup.cache.user_cache_dir",
            lambda _prog: str(tmp_path),
        )
        reporter = Reporter(stats=Stats())
        cache = LookupCache(cache_expiry_days=30, reporter=reporter)

        found, lang = cache.check_cache("tv", "never-saved", "")

        assert not found
        assert lang is None
        assert reporter.stats.db_cache_hits == 0
        assert reporter.stats.db_no_results == []

    def test_file_miss_records_no_result(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "nudebomb.lookup.cache.user_cache_dir",
            lambda _prog: str(tmp_path),
        )
        reporter = Reporter(stats=Stats())
        cache = LookupCache(cache_expiry_days=30, reporter=reporter)

        # Empty-language save (a miss cached to disk).
        cache.save_file("movie", "Unknown", "1999", language="")
        # Evict the mem cache so we hit the file layer.
        cache._mem_cache.clear()

        found, lang = cache.check_cache("movie", "Unknown", "1999")

        assert found
        assert lang is None
        assert reporter.stats.db_cache_hits == 1
        assert len(reporter.stats.db_no_results) == 1


class TestCacheEntry:
    """CacheEntry expiry semantics."""

    def test_fresh_hit_ignores_short_expiry(self) -> None:
        """The configurable miss expiry does not apply to hits."""
        entry = CacheEntry(cached_at=time.time(), language="eng")
        assert not entry.is_expired(expiry_days=1)

    def test_ancient_hit_expires_on_long_horizon(self) -> None:
        """Positive entries self-heal after POSITIVE_EXPIRY_DAYS."""
        entry = CacheEntry(cached_at=0.0, language="eng")
        assert entry.is_expired(expiry_days=1)

    def test_miss_expires_after_window(self) -> None:
        entry = CacheEntry(cached_at=0.0, language="")
        assert entry.is_expired(expiry_days=30)


class TestLookupCacheDedup:
    """Populated caches dedupe subsequent calls."""

    def test_title_hit_after_save(self, tmp_cache: LookupCache) -> None:
        tmp_cache.save_file("movie", "Dune", "2021", db_id="123", language="eng")
        # Even if we clear the mem cache, the file cache should hit.
        tmp_cache._mem_cache.clear()
        found, lang = tmp_cache.check_cache("movie", "Dune", "2021")
        assert found
        assert lang == "eng"

    def test_id_hit_after_save(self, tmp_cache: LookupCache) -> None:
        tmp_cache.save_id("tv", "tvdb", "81189", db_id="81189", language="eng")
        tmp_cache._id_mem_cache.clear()
        found, lang = tmp_cache.check_id_cache("tv", "tvdb", "81189")
        assert found
        assert lang == "eng"


class TestAtomicWrite:
    """Writes use tmp+rename so readers never see torn content."""

    def test_partial_write_not_observable(self, tmp_cache: LookupCache) -> None:
        # Write, then verify no leftover .tmp file.
        tmp_cache.save_file("movie", "Atom", "2024", language="eng")
        path = tmp_cache._cache_path("movie", "Atom", "2024")
        assert path.is_file()
        # No sibling tmp files left behind.
        siblings = list(path.parent.iterdir())
        assert all(not s.name.endswith(".tmp") for s in siblings)


class TestTempCacheRootIsolation:
    """Sanity: the tmp_cache fixture keeps us out of the real user cache dir."""

    def test_cache_root_is_tmp(self, tmp_cache: LookupCache, tmp_path: Path) -> None:
        assert tmp_cache._cache_root == tmp_path


class TestAtomicWriteHelper:
    """The _atomic_write_text helper is exercised via save_file above."""

    def test_write_and_read_roundtrip(self, tmp_path: Path) -> None:
        """Basic smoke test using the module-level helper."""
        from nudebomb.atomic import atomic_write_text

        target = tmp_path / "target.json"
        atomic_write_text(target, '{"hello": "world"}')
        assert target.read_text() == '{"hello": "world"}'

    def test_overwrite(self, tmp_path: Path) -> None:
        from nudebomb.atomic import atomic_write_text

        target = tmp_path / "target.json"
        atomic_write_text(target, "first")
        atomic_write_text(target, "second")
        assert target.read_text() == "second"


class TestCorruptCacheFiles:
    """Corrupt or stale-schema cache files are misses and get deleted."""

    def test_schema_drift_treated_as_miss(self, tmp_cache: LookupCache) -> None:
        tmp_cache.save_file("movie", "Drift", "2024", language="eng")
        path = tmp_cache._cache_path("movie", "Drift", "2024")
        path.write_text('{"unexpected_key": 1, "language": "eng"}')
        tmp_cache._mem_cache.clear()

        found, _lang = tmp_cache.check_cache("movie", "Drift", "2024")

        assert not found
        assert not path.exists()

    def test_non_dict_json_treated_as_miss(self, tmp_cache: LookupCache) -> None:
        path = tmp_cache._cache_path("movie", "Listy", "")
        path.write_text("[1, 2, 3]")

        found, _lang = tmp_cache.check_cache("movie", "Listy", "")

        assert not found
        assert not path.exists()


class TestGenericTitleCachePersistence:
    """With no media type set, disk hits under the result's type are found."""

    def test_cross_instance_file_cache_hit(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Register the custom DBHIT loguru level the hit path logs at.
        setup_logging(0)
        monkeypatch.setattr(
            "nudebomb.lookup.cache.user_cache_dir",
            lambda _prog: str(tmp_path),
        )

        class _Cfg:
            tmdb_api_key = "fake"
            cache_expiry_days = 30
            media_type = None
            verbose = 0

        result = {
            "media_type": "movie",
            "id": 1,
            "title": "Dune",
            "release_date": "2021-10-22",
            "original_language": "en",
        }
        parsed = ParseResult(
            title="Dune", year="2021", tmdb_id="", imdb_id="", tvdb_id=""
        )

        first = TMDBLookup(_Cfg(), Reporter(stats=Stats()))  # pyright: ignore[reportArgumentType], #ty: ignore[invalid-argument-type]
        with patch.object(first, "_search_tmdb", return_value=result):
            assert first._lookup_by_title_language("Dune", "2021", parsed) == "eng"

        # A new instance (fresh mem cache) must hit the file cache, not
        # the API — before the fix the write went under movie/ while the
        # read looked in the root, so every run re-queried.
        second = TMDBLookup(_Cfg(), Reporter(stats=Stats()))  # pyright: ignore[reportArgumentType], #ty: ignore[invalid-argument-type]
        with patch.object(
            second, "_search_tmdb", side_effect=AssertionError("unexpected API call")
        ):
            assert second._lookup_by_title_language("Dune", "2021", parsed) == "eng"
