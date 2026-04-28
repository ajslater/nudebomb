"""Tests for the summary module."""

import io
from pathlib import Path

from rich.console import Console

from nudebomb.log.summary import Stats, render

__all__ = ()


class TestStats:
    """Stats record_* methods are thread-safe and accumulate correctly."""

    def test_counters_default_zero(self) -> None:
        stats = Stats()
        assert stats.ignored == 0
        assert stats.db_cache_hits == 0
        assert stats.stripped == []

    def test_record_counters(self) -> None:
        stats = Stats()
        stats.record_ignored()
        stats.record_skipped_timestamp()
        stats.record_already_stripped()
        stats.record_db_cache_hit()
        stats.record_db_remote_hit()
        stats.record_langfile_hit()
        assert stats.ignored == 1
        assert stats.skipped_timestamp == 1
        assert stats.already_stripped == 1
        assert stats.db_cache_hits == 1
        assert stats.db_remote_hits == 1
        assert stats.langfile_hits == 1

    def test_record_lists(self) -> None:
        stats = Stats()
        stats.record_stripped(Path("/tmp/a.mkv"))  # noqa: S108
        stats.record_dry_run(Path("/tmp/b.mkv"))  # noqa: S108
        stats.record_warning(Path("/tmp/c.mkv"), "weird")  # noqa: S108
        stats.record_error(Path("/tmp/d.mkv"), "boom")  # noqa: S108
        stats.record_db_no_result("missing")
        stats.record_db_remote_error("rate limited")

        assert stats.stripped == [Path("/tmp/a.mkv")]  # noqa: S108
        assert stats.dry_run == [Path("/tmp/b.mkv")]  # noqa: S108
        assert stats.warnings == [(Path("/tmp/c.mkv"), "weird")]  # noqa: S108
        assert stats.errors == [(Path("/tmp/d.mkv"), "boom")]  # noqa: S108
        assert stats.db_no_results == ["missing"]
        assert stats.db_remote_errors == ["rate limited"]


class TestRender:
    """render() prints a counts table and itemized lists."""

    def test_empty_stats_renders_just_table(self) -> None:
        buffer = io.StringIO()
        console = Console(file=buffer, force_terminal=False, width=120)
        render(Stats(), console)
        output = buffer.getvalue()
        # Counts table is always present
        assert "Summary" in output
        # No itemized sections when lists are empty (the table includes
        # "Errors" as a row header — match the bulleted-list header form)
        assert "Stripped tracks:" not in output
        assert "Warnings:" not in output
        assert "Errors:" not in output

    def test_renders_itemized_lists(self) -> None:
        stats = Stats()
        stats.record_stripped(Path("/a.mkv"))
        stats.record_dry_run(Path("/b.mkv"))
        stats.record_warning(Path("/c.mkv"), "weird")
        stats.record_error(Path("/d.mkv"), "boom")
        stats.record_db_no_result("missing one")
        stats.record_db_remote_error("rate limited")

        buffer = io.StringIO()
        console = Console(file=buffer, force_terminal=False, width=120)
        render(stats, console)
        output = buffer.getvalue()

        assert "Stripped tracks" in output
        assert "/a.mkv" in output
        assert "Not remuxed (dry run)" in output
        assert "/b.mkv" in output
        assert "Warnings" in output
        assert "weird" in output
        assert "Errors" in output
        assert "boom" in output
        assert "DB lookups with no result" in output
        assert "missing one" in output
        assert "Remote DB errors" in output
        assert "rate limited" in output
