"""Tests for the lookup module: cache thread-safety, error handling."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Final
from unittest.mock import patch

import pytest
from requests.exceptions import HTTPError
from requests.models import Response

from nudebomb.log.reporter import Reporter
from nudebomb.log.summary import Stats
from nudebomb.lookup.cache import CacheEntry, LookupCache
from nudebomb.lookup.parser import ParseResult
from nudebomb.lookup.tmdb import TMDBLookup
from nudebomb.lookup.tvdb import TVDBLookup, _is_tvdb_error_dict

__all__ = ()

_N_THREADS: Final = 8
_N_ITERATIONS: Final = 200


@pytest.fixture
def tmp_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> LookupCache:
    """Build a LookupCache rooted at a temp dir so tests are isolated."""
    monkeypatch.setattr(
        "nudebomb.lookup.cache.user_cache_dir",
        lambda _prog: str(tmp_path),
    )
    return LookupCache(cache_expiry_days=30)


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


class TestTVDBErrorDict:
    """TVDB returns errors as dicts with 'code' + 'message'."""

    def test_rate_limit_dict(self) -> None:
        assert _is_tvdb_error_dict({"code": 429, "message": "rate limited"})

    def test_server_error_dict(self) -> None:
        assert _is_tvdb_error_dict({"code": 503, "message": "down"})

    def test_not_modified_not_an_error(self) -> None:
        """304 Not-Modified has a code but is a cache directive, not a failure."""
        assert not _is_tvdb_error_dict({"code": 304, "message": "Not-Modified"})

    def test_plain_result_is_not_an_error(self) -> None:
        assert not _is_tvdb_error_dict({"name": "Breaking Bad", "id": 81189})

    def test_non_dict_is_not_an_error(self) -> None:
        assert not _is_tvdb_error_dict(None)
        assert not _is_tvdb_error_dict("string")
        assert not _is_tvdb_error_dict([1, 2, 3])


class TestTMDBErrorHandling:
    """Rate-limit and error responses must NOT poison the cache."""

    @pytest.fixture
    def tmdb(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> tuple[TMDBLookup, Reporter]:
        monkeypatch.setattr(
            "nudebomb.lookup.cache.user_cache_dir",
            lambda _prog: str(tmp_path),
        )

        class _Cfg:
            tmdb_api_key = "fake"
            cache_expiry_days = 30
            media_type = "movie"
            verbose = 0

        reporter = Reporter(stats=Stats())
        return TMDBLookup(_Cfg(), reporter), reporter  # pyright: ignore[reportArgumentType],#ty:  ignore[invalid-argument-type]

    @staticmethod
    def _make_http_error(status: int) -> HTTPError:
        resp = Response()
        resp.status_code = status
        exc = HTTPError()
        exc.response = resp
        return exc

    def test_rate_limit_does_not_cache_miss(
        self, tmdb: tuple[TMDBLookup, Reporter]
    ) -> None:
        """429 returns None and leaves the cache clean for a retry."""
        tmdb_lookup, reporter = tmdb
        parsed = ParseResult(
            title="Foo", year="2024", tmdb_id="", imdb_id="", tvdb_id=""
        )

        with patch.object(
            tmdb_lookup, "_search_tmdb", side_effect=self._make_http_error(429)
        ):
            lang = tmdb_lookup._lookup_by_title_language("Foo", "2024", parsed)

        assert lang is None
        # No cache entry was written.
        found, _lang = tmdb_lookup._cache.check_cache("movie", "Foo", "2024")
        assert not found
        # A rate-limit error was recorded.
        assert reporter.stats.db_remote_errors

    def test_generic_http_error_does_not_cache_miss(
        self, tmdb: tuple[TMDBLookup, Reporter]
    ) -> None:
        tmdb_lookup, reporter = tmdb
        parsed = ParseResult(
            title="Foo", year="2024", tmdb_id="", imdb_id="", tvdb_id=""
        )
        with patch.object(
            tmdb_lookup, "_search_tmdb", side_effect=self._make_http_error(500)
        ):
            lang = tmdb_lookup._lookup_by_title_language("Foo", "2024", parsed)

        assert lang is None
        found, _lang = tmdb_lookup._cache.check_cache("movie", "Foo", "2024")
        assert not found
        assert reporter.stats.db_remote_errors

    def test_no_result_is_cached_as_miss(
        self, tmdb: tuple[TMDBLookup, Reporter]
    ) -> None:
        """A genuine empty response IS cached (as a miss) to avoid re-hitting."""
        tmdb_lookup, _reporter = tmdb
        parsed = ParseResult(
            title="Foo", year="2024", tmdb_id="", imdb_id="", tvdb_id=""
        )
        with patch.object(tmdb_lookup, "_search_tmdb", return_value=None):
            lang = tmdb_lookup._lookup_by_title_language("Foo", "2024", parsed)

        assert lang is None
        found, lang = tmdb_lookup._cache.check_cache("movie", "Foo", "2024")
        assert found
        assert lang is None


class TestTVDBErrorHandling:
    """TVDB error-dicts are detected and not cached."""

    @pytest.fixture
    def tvdb(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> tuple[TVDBLookup, Reporter]:
        monkeypatch.setattr(
            "nudebomb.lookup.cache.user_cache_dir",
            lambda _prog: str(tmp_path),
        )

        # tvdb_v4_official.TVDB.__init__ makes a live HTTP call to log in.
        # Patch it to a no-op so we can construct the lookup offline.
        with patch("tvdb_v4_official.TVDB") as mock_tvdb:
            mock_tvdb.return_value = object()  # placeholder

            class _Cfg:
                tvdb_api_key = "fake"
                cache_expiry_days = 30
                verbose = 0

            reporter = Reporter(stats=Stats())
            return TVDBLookup(_Cfg(), reporter), reporter  # pyright: ignore[reportArgumentType], #ty: ignore[invalid-argument-type]

    def test_rate_limit_dict_does_not_cache(
        self, tvdb: tuple[TVDBLookup, Reporter]
    ) -> None:
        tvdb_lookup, reporter = tvdb
        parsed = ParseResult(title="Foo", year="", tmdb_id="", imdb_id="", tvdb_id="")
        rate_limited = {"code": 429, "message": "rate limited"}
        with patch.object(tvdb_lookup, "_search_tvdb", return_value=rate_limited):
            lang = tvdb_lookup._lookup_by_title_language("Foo", parsed)

        assert lang is None
        found, _lang = tvdb_lookup._cache.check_cache("tv", "Foo", "")
        assert not found
        assert reporter.stats.db_remote_errors

    def test_server_error_dict_does_not_cache(
        self, tvdb: tuple[TVDBLookup, Reporter]
    ) -> None:
        tvdb_lookup, reporter = tvdb
        parsed = ParseResult(title="Foo", year="", tmdb_id="", imdb_id="", tvdb_id="")
        server_error = {"code": 500, "message": "down"}
        with patch.object(tvdb_lookup, "_search_tvdb", return_value=server_error):
            lang = tvdb_lookup._lookup_by_title_language("Foo", parsed)

        assert lang is None
        found, _lang = tvdb_lookup._cache.check_cache("tv", "Foo", "")
        assert not found
        assert reporter.stats.db_remote_errors


class TestCacheEntry:
    """CacheEntry expiry semantics."""

    def test_hit_never_expires(self) -> None:
        entry = CacheEntry(cached_at=0.0, language="eng")
        assert not entry.is_expired(expiry_days=1)

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
        from nudebomb.lookup.cache import _atomic_write_text

        target = tmp_path / "target.json"
        _atomic_write_text(target, '{"hello": "world"}')
        assert target.read_text() == '{"hello": "world"}'

    def test_overwrite(self, tmp_path: Path) -> None:
        from nudebomb.lookup.cache import _atomic_write_text

        target = tmp_path / "target.json"
        _atomic_write_text(target, "first")
        _atomic_write_text(target, "second")
        assert target.read_text() == "second"
