"""Tests for the lookup backends: error handling, queries, title matching."""

import socket
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from urllib.error import URLError

import pytest
from requests.exceptions import HTTPError
from requests.models import Response

from nudebomb.log.reporter import Reporter
from nudebomb.log.summary import Stats
from nudebomb.lookup.cache import LookupCache
from nudebomb.lookup.media_type import MediaType
from nudebomb.lookup.parser import ParseResult
from nudebomb.lookup.tmdb import TMDBLookup, _result_titles, _result_year
from nudebomb.lookup.tvdb import (
    TVDBLookup,
    _is_tvdb_error_dict,
    connect_tvdb,
)
from nudebomb.lookup.tvdb import (
    _result_titles as tvdb_result_titles,
)
from nudebomb.lookup.tvdb import (
    _result_year as tvdb_result_year,
)
from nudebomb.lookup.util import (
    LOOKUP_TIMEOUT_SECONDS,
    best_title_match,
    redact_api_key,
)

__all__ = ()


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
    ) -> Iterator[tuple[TVDBLookup, Reporter]]:
        monkeypatch.setattr(
            "nudebomb.lookup.cache.user_cache_dir",
            lambda _prog: str(tmp_path),
        )

        # tvdb_v4_official.TVDB.__init__ makes a live HTTP call to log in,
        # which the lookup does on its first query. Patch it to a no-op for
        # the whole test so queries run offline.
        with patch("tvdb_v4_official.TVDB") as mock_tvdb:
            mock_tvdb.return_value = object()  # placeholder

            class _Cfg:
                tvdb_api_key = "fake"
                cache_expiry_days = 30
                verbose = 0

            reporter = Reporter(stats=Stats())
            yield TVDBLookup(_Cfg(), reporter), reporter  # pyright: ignore[reportArgumentType], #ty: ignore[invalid-argument-type]

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


_TVDB_KEY = "SECRET-TVDB-KEY"
# What tvdb_v4_official's login raises for a rejected key and for no network.
TVDB_LOGIN_ERRORS = (
    pytest.param(
        Exception("Code:HTTP Error 401: Unauthorized, InvalidAPIKey"), id="bad-key"
    ),
    pytest.param(URLError("no network"), id="no-network"),
)


class TestTVDBLogin:
    """TVDB logs in on the first remote query; a failed login disables only TVDB."""

    @staticmethod
    def _lookup(cache: LookupCache) -> tuple[TVDBLookup, Reporter]:
        class _Cfg:
            tvdb_api_key = _TVDB_KEY
            cache_expiry_days = 30
            verbose = 0

        reporter = Reporter(stats=Stats())
        return TVDBLookup(_Cfg(), reporter, cache), reporter  # pyright: ignore[reportArgumentType], #ty: ignore[invalid-argument-type]

    def test_construction_does_not_log_in(self, tmp_cache: LookupCache) -> None:
        with patch("tvdb_v4_official.TVDB") as mock_tvdb:
            self._lookup(tmp_cache)
        mock_tvdb.assert_not_called()

    def test_cache_hit_needs_no_login(self, tmp_cache: LookupCache) -> None:
        tmp_cache.save_file(MediaType.TV, "Cowboy Bebop", "", language="jpn")
        tvdb_lookup, _reporter = self._lookup(tmp_cache)
        with patch(
            "tvdb_v4_official.TVDB", side_effect=URLError("no network")
        ) as mock_tvdb:
            lang = tvdb_lookup.lookup_language(Path("Cowboy Bebop - S01E01.mkv"))
        assert lang == "jpn"
        mock_tvdb.assert_not_called()

    @pytest.mark.parametrize("login_error", TVDB_LOGIN_ERRORS)
    def test_login_failure_reported_once(
        self, tmp_cache: LookupCache, login_error: Exception
    ) -> None:
        tvdb_lookup, reporter = self._lookup(tmp_cache)
        with patch("tvdb_v4_official.TVDB", side_effect=login_error) as mock_tvdb:
            langs = [
                tvdb_lookup.lookup_language(Path(name))
                for name in ("Cowboy Bebop - S01E01.mkv", "Trigun - S01E01.mkv")
            ]

        assert langs == [None, None]
        # No retry per file: one failed login disables TVDB for the run.
        mock_tvdb.assert_called_once()
        (msg,) = reporter.stats.db_remote_errors
        assert msg.startswith("TVDB login failed")
        assert str(login_error) in msg
        assert _TVDB_KEY not in msg
        # Not a miss: nothing is cached, so the next run tries again.
        found, _lang = tmp_cache.check_cache(MediaType.TV, "Cowboy Bebop", "")
        assert not found


class _FakeSearch:
    """Captures the query passed to tmdbsimple's search methods."""

    def __init__(self) -> None:
        self.results: list[dict] = []
        self.calls: dict[str, object] = {}

    def multi(self, query: str) -> None:
        self.calls["multi"] = query

    def movie(self, query: str, year: str) -> None:
        self.calls["movie"] = (query, year)

    def tv(self, query: str, first_air_date_year: str) -> None:
        self.calls["tv"] = (query, first_air_date_year)


class TestTMDBQueryConstruction:
    """The generic multi search must not glue the year into the query text."""

    @staticmethod
    def _lookup(
        monkeypatch: pytest.MonkeyPatch,
        cache: LookupCache,
        media_type: str | None,
    ) -> tuple[TMDBLookup, _FakeSearch]:
        fake = _FakeSearch()
        monkeypatch.setattr("nudebomb.lookup.tmdb.tmdb.Search", lambda: fake)
        cfg = SimpleNamespace(
            tmdb_api_key="fake",
            cache_expiry_days=30,
            media_type=media_type,
            verbose=0,
        )
        lookup = TMDBLookup(cfg, Reporter(stats=Stats()), cache)  # pyright: ignore[reportArgumentType], # ty: ignore[invalid-argument-type]
        return lookup, fake

    def test_multi_query_omits_year(
        self, monkeypatch: pytest.MonkeyPatch, tmp_cache: LookupCache
    ) -> None:
        lookup, fake = self._lookup(monkeypatch, tmp_cache, None)
        lookup._search_tmdb("Margin Call", "2011")
        assert fake.calls["multi"] == "Margin Call"

    def test_movie_query_keeps_year_filter(
        self, monkeypatch: pytest.MonkeyPatch, tmp_cache: LookupCache
    ) -> None:
        lookup, fake = self._lookup(monkeypatch, tmp_cache, "movie")
        lookup._search_tmdb("Margin Call", "2011")
        assert fake.calls["movie"] == ("Margin Call", "2011")

    def test_per_directory_media_type_reaches_search(
        self, monkeypatch: pytest.MonkeyPatch, tmp_cache: LookupCache
    ) -> None:
        """A directory-config media_type (global unset) drives a movie search."""
        lookup, fake = self._lookup(monkeypatch, tmp_cache, None)
        lookup.lookup_language(Path("Limitless (2011).mkv"), "movie")
        assert "multi" not in fake.calls  # not the year-losing multi search
        assert fake.calls["movie"] == ("Limitless", "2011")


class TestBestTitleMatch:
    """Search results are verified against the query title before use."""

    def test_wrong_first_result_rejected(self) -> None:
        results = [
            {"title": "Totally Different", "release_date": "1999-01-01"},
            {"title": "Dune", "release_date": "2021-10-22"},
        ]
        match = best_title_match(results, "Dune", "", _result_titles, _result_year)
        assert match is not None
        assert match["title"] == "Dune"

    def test_year_disambiguates_same_titles(self) -> None:
        results = [
            {"title": "Dune", "release_date": "2021-10-22"},
            {"title": "Dune", "release_date": "1984-12-14"},
        ]
        match = best_title_match(results, "Dune", "1984", _result_titles, _result_year)
        assert match is not None
        assert match["release_date"] == "1984-12-14"

    def test_no_acceptable_match_returns_none(self) -> None:
        results = [{"title": "Unrelated Thing", "release_date": "2000-01-01"}]
        assert (
            best_title_match(results, "Dune", "", _result_titles, _result_year) is None
        )

    def test_fuzzy_match_accepted(self) -> None:
        results = [{"name": "Battlestar Galactica (1978)", "first_air_date": "1978"}]
        match = best_title_match(
            results, "Battlestar Galactica", "", _result_titles, _result_year
        )
        assert match is not None

    def test_tmdb_original_title_matches(self) -> None:
        """A romanized query matches a TMDB result via original_title."""
        results = [
            {
                "title": "Localized Name",
                "original_title": "Real Title",
                "release_date": "2020-01-01",
            }
        ]
        match = best_title_match(
            results, "Real Title", "", _result_titles, _result_year
        )
        assert match is results[0]


class TestTVDBAliasMatch:
    """A romanized query matches a show whose canonical TVDB name is non-Latin."""

    def test_alias_matches_romanized_query(self) -> None:
        # Colon dropped/rewritten in the on-disk name; canonical is katakana.
        results = [
            {
                "name": "タイトル サブタイトル",
                "aliases": ["Title: Subtitle"],
                "year": "2020",
            }
        ]
        for query in ("Title - Subtitle", "Title- Subtitle", "Title Subtitle"):
            match = best_title_match(
                [results[0]], query, "", tvdb_result_titles, tvdb_result_year
            )
            assert match is results[0], query

    def test_translation_matches_romanized_query(self) -> None:
        results = [
            {
                "name": "タイトル",
                "translations": {"eng": "Title: Subtitle"},
                "year": "2020",
            }
        ]
        match = best_title_match(
            results, "Title Subtitle", "", tvdb_result_titles, tvdb_result_year
        )
        assert match is results[0]

    def test_non_matching_aliases_still_rejected(self) -> None:
        results = [{"name": "別の番組", "aliases": ["A Different Show"]}]
        match = best_title_match(
            results, "Title Subtitle", "", tvdb_result_titles, tvdb_result_year
        )
        assert match is None

    def test_missing_or_malformed_alias_fields(self) -> None:
        """Absent/odd aliases/translations don't crash; name still matches."""
        results = [{"name": "Title Subtitle", "aliases": None, "translations": []}]
        match = best_title_match(
            results, "Title Subtitle", "", tvdb_result_titles, tvdb_result_year
        )
        assert match is results[0]


class TestSecretRedaction:
    """API keys embedded in exception text never reach logs or stats."""

    def test_api_key_redacted(self) -> None:
        raw = (
            "404 Client Error: Not Found for url: "
            "https://api.themoviedb.org/3/search/movie?api_key=SECRET123&query=Alien"
        )
        redacted = redact_api_key(raw)
        assert "SECRET123" not in redacted
        assert "api_key=REDACTED" in redacted
        assert "query=Alien" in redacted


class TestTimeouts:
    """Both lookup backends get an HTTP timeout configured."""

    def test_tmdb_timeout_configured(self, tmp_cache: LookupCache) -> None:
        import tmdbsimple

        class _Cfg:
            tmdb_api_key = "fake"
            cache_expiry_days = 30
            media_type = None
            verbose = 0

        TMDBLookup(_Cfg(), Reporter(stats=Stats()), tmp_cache)  # pyright: ignore[reportArgumentType], #ty: ignore[invalid-argument-type]
        assert tmdbsimple.REQUESTS_TIMEOUT == LOOKUP_TIMEOUT_SECONDS

    def test_tvdb_socket_timeout_configured(self) -> None:
        # The default is process-wide, so clear it first or an earlier
        # test's login would make this pass on its own.
        old_timeout = socket.getdefaulttimeout()
        socket.setdefaulttimeout(None)
        try:
            with patch("tvdb_v4_official.TVDB"):
                connect_tvdb("fake")
            assert socket.getdefaulttimeout() == LOOKUP_TIMEOUT_SECONDS
        finally:
            socket.setdefaulttimeout(old_timeout)
