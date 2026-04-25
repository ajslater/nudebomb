"""Tests for Walk-level lookup dispatch, dedupe, and event replay."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from nudebomb.lookup.util import LogEvent, LookupResult
from nudebomb.walk import Walk

__all__ = ()


def _make_walk(
    monkeypatch: pytest.MonkeyPatch,
    *,
    media_type: str = "movie",
    tmdb: MagicMock | None = None,
    tvdb: MagicMock | None = None,
) -> Walk:
    """Build a Walk with TMDB/TVDB clients pre-patched for offline testing."""
    # Stub out the lookup client construction so Walk.__init__ doesn't try
    # to reach the network.
    monkeypatch.setattr("nudebomb.walk.TMDBLookup", lambda _cfg: tmdb)
    monkeypatch.setattr("nudebomb.walk.TVDBLookup", lambda _cfg: tvdb)

    cfg = SimpleNamespace(
        tmdb_api_key="fake" if tmdb is not None else None,
        tvdb_api_key="fake" if tvdb is not None else None,
        media_type=media_type,
        languages=("eng",),
        verbose=0,
        ignore=(),
        symlinks=True,
        cache_expiry_days=30,
        after=None,
        lookup_workers=4,
    )
    return Walk(cfg)  # pyright: ignore[reportArgumentType], #ty: ignore[invalid-argument-type]


class TestLookupKey:
    """Canonical cache keys dedupe across files with the same target."""

    def test_tvdb_id_in_filename_wins(self, monkeypatch: pytest.MonkeyPatch) -> None:
        walk = _make_walk(monkeypatch, media_type="tv", tvdb=MagicMock())
        key = walk._lookup_key(Path("Breaking Bad - S01E01 {tvdb-81189}.mkv"))
        assert key == ("tv", "tvdb", "81189")

    def test_tmdb_id_in_filename_wins(self, monkeypatch: pytest.MonkeyPatch) -> None:
        walk = _make_walk(monkeypatch, tmdb=MagicMock())
        key = walk._lookup_key(Path("Dune {tmdb-438631}.mkv"))
        assert key == ("", "tmdb", "438631")

    def test_title_and_year_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        walk = _make_walk(monkeypatch, tmdb=MagicMock())
        key = walk._lookup_key(Path("Dune (2021) 1080p.mkv"))
        assert key == ("movie", "Dune", "2021")

    def test_two_episodes_share_a_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Two episodes of the same show dedupe to a single lookup."""
        walk = _make_walk(monkeypatch, media_type="tv", tvdb=MagicMock())
        key_a = walk._lookup_key(Path("GI Robot Adventures - S01E01 - pilot.mkv"))
        key_b = walk._lookup_key(Path("GI Robot Adventures - S01E02 - the killing.mkv"))
        assert key_a == key_b

    def test_no_key_for_empty_title(self, monkeypatch: pytest.MonkeyPatch) -> None:
        walk = _make_walk(monkeypatch, tmdb=MagicMock())
        assert walk._lookup_key(Path(".mkv")) is None


class TestSubmitLookupDedup:
    """_submit_lookup returns the same future for identical keys."""

    def test_same_key_same_future(self, monkeypatch: pytest.MonkeyPatch) -> None:
        tmdb = MagicMock()
        tmdb.lookup_language.return_value = LookupResult(lang="eng")
        walk = _make_walk(monkeypatch, tmdb=tmdb)

        with ThreadPoolExecutor(max_workers=2) as executor:
            walk._executor = executor
            fut_a = walk._submit_lookup(Path("Dune (2021) 1080p.mkv"))
            fut_b = walk._submit_lookup(Path("Dune (2021) 720p.mkv"))
            assert fut_a is fut_b
            assert fut_a is not None
            fut_a.result()  # drain

        # Only one lookup call was made across both submissions.
        assert tmdb.lookup_language.call_count == 1

    def test_different_keys_different_futures(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        tmdb = MagicMock()
        tmdb.lookup_language.return_value = LookupResult(lang="eng")
        walk = _make_walk(monkeypatch, tmdb=tmdb)
        expected_calls = 2

        with ThreadPoolExecutor(max_workers=2) as executor:
            walk._executor = executor
            fut_a = walk._submit_lookup(Path("Dune (2021) 1080p.mkv"))
            fut_b = walk._submit_lookup(Path("Arrival (2016) 1080p.mkv"))
            assert fut_a is not fut_b
            assert fut_a is not None
            assert fut_b is not None
            fut_a.result()
            fut_b.result()

        assert tmdb.lookup_language.call_count == expected_calls

    def test_no_backend_no_future(self, monkeypatch: pytest.MonkeyPatch) -> None:
        walk = _make_walk(monkeypatch)  # no tmdb or tvdb
        assert walk._submit_lookup(Path("Dune (2021).mkv")) is None

    def test_no_executor_no_future(self, monkeypatch: pytest.MonkeyPatch) -> None:
        walk = _make_walk(monkeypatch, tmdb=MagicMock())
        assert walk._submit_lookup(Path("Dune (2021).mkv")) is None


class TestDoLookup:
    """_do_lookup honors the TVDB-first-then-TMDB cascade."""

    def test_tvdb_tv_hit_skips_tmdb(self, monkeypatch: pytest.MonkeyPatch) -> None:
        tvdb = MagicMock()
        tvdb.lookup_language.return_value = LookupResult(lang="jpn")
        tmdb = MagicMock()
        walk = _make_walk(monkeypatch, media_type="tv", tmdb=tmdb, tvdb=tvdb)

        result = walk._do_lookup(Path("Cowboy Bebop.mkv"))

        assert result.lang == "jpn"
        assert tvdb.lookup_language.call_count == 1
        assert tmdb.lookup_language.call_count == 0

    def test_tvdb_miss_falls_through_to_tmdb(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        tvdb = MagicMock()
        tvdb.lookup_language.return_value = LookupResult(lang=None)
        tmdb = MagicMock()
        tmdb.lookup_language.return_value = LookupResult(lang="eng")
        walk = _make_walk(monkeypatch, media_type="tv", tmdb=tmdb, tvdb=tvdb)

        result = walk._do_lookup(Path("Breaking Bad.mkv"))

        assert result.lang == "eng"
        assert tvdb.lookup_language.call_count == 1
        assert tmdb.lookup_language.call_count == 1

    def test_movie_skips_tvdb(self, monkeypatch: pytest.MonkeyPatch) -> None:
        tvdb = MagicMock()
        tmdb = MagicMock()
        tmdb.lookup_language.return_value = LookupResult(lang="eng")
        walk = _make_walk(monkeypatch, media_type="movie", tmdb=tmdb, tvdb=tvdb)

        walk._do_lookup(Path("Dune (2021).mkv"))
        assert tvdb.lookup_language.call_count == 0
        assert tmdb.lookup_language.call_count == 1

    def test_events_are_combined(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Events from both backends flow through to the caller."""
        tvdb = MagicMock()
        tvdb.lookup_language.return_value = LookupResult(
            lang=None, events=(LogEvent("lookup_no_result", "tvdb miss"),)
        )
        tmdb = MagicMock()
        tmdb.lookup_language.return_value = LookupResult(
            lang="eng", events=(LogEvent("lookup_hit", "tmdb hit"),)
        )
        walk = _make_walk(monkeypatch, media_type="tv", tmdb=tmdb, tvdb=tvdb)

        result = walk._do_lookup(Path("Foo.mkv"))

        methods = [e.method for e in result.events]
        assert methods == ["lookup_no_result", "lookup_hit"]


class TestReplayEvents:
    """Events get replayed on the main thread's Printer."""

    def test_replay_calls_printer_methods(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        walk = _make_walk(monkeypatch, tmdb=MagicMock())
        walk._printer = MagicMock()

        events = (
            LogEvent("lookup_hit", "hit: Foo"),
            LogEvent("lookup_no_result", "miss: Bar"),
            LogEvent("lookup_rate_limited", "slow down"),
        )
        walk._replay_events(events)

        walk._printer.lookup_hit.assert_called_once_with("hit: Foo")
        walk._printer.lookup_no_result.assert_called_once_with("miss: Bar")
        walk._printer.lookup_rate_limited.assert_called_once_with("slow down")

    def test_unknown_method_falls_back_to_warn(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        walk = _make_walk(monkeypatch, tmdb=MagicMock())
        walk._printer = MagicMock(spec=["warn"])

        walk._replay_events((LogEvent("bogus_method", "hello"),))

        walk._printer.warn.assert_called_once()
