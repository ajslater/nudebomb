"""Tests for the summary module."""

import io
from pathlib import Path

import pytest
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


def _render(stats: Stats) -> str:
    buffer = io.StringIO()
    console = Console(file=buffer, force_terminal=False, width=120)
    render(stats, console)
    return buffer.getvalue()


class TestRender:
    """render() prints a counts table and itemized lists."""

    def test_empty_stats_renders_just_table(self) -> None:
        output = _render(Stats())
        # Counts table is always present
        assert "Summary" in output
        # No itemized sections when lists are empty (the table includes
        # "Errors" as a row header — match the bulleted-list header form)
        assert "Stripped tracks:" not in output
        assert "Warnings:" not in output
        assert "Errors:" not in output

    @pytest.mark.parametrize(
        ("record", "args", "header", "content"),
        [
            ("record_stripped", (Path("/a.mkv"),), "Stripped tracks", "/a.mkv"),
            (
                "record_dry_run",
                (Path("/b.mkv"),),
                "Not remuxed (dry run)",
                "/b.mkv",
            ),
            ("record_warning", (Path("/c.mkv"), "weird"), "Warnings", "weird"),
            ("record_error", (Path("/d.mkv"), "boom"), "Errors", "boom"),
            (
                "record_db_no_result",
                ("missing one",),
                "DB lookups with no result",
                "missing one",
            ),
            (
                "record_db_remote_error",
                ("rate limited",),
                "Remote DB errors",
                "rate limited",
            ),
        ],
    )
    def test_renders_itemized_section(
        self,
        record: str,
        args: tuple[object, ...],
        header: str,
        content: str,
    ) -> None:
        """Each itemized section appears with its header and contents."""
        stats = Stats(
            timestamps_active=True,
            dry_run_active=True,
            remote_db_active=True,
        )
        getattr(stats, record)(*args)

        output = _render(stats)

        assert header in output
        assert content in output


class TestConditionalRows:
    """Mode-specific summary rows are hidden when their mode is inactive."""

    @pytest.mark.parametrize(
        "row",
        [
            "Skipped (timestamp)",
            "Not remuxed (dry run)",
            "Remote DB hits",
            "Warnings",
            "Errors",
        ],
    )
    def test_default_hides_mode_specific_row(self, row: str) -> None:
        """Mode-specific rows are hidden when no mode flag is set."""
        assert row not in _render(Stats())

    @pytest.mark.parametrize(
        "row",
        [
            "Ignored",
            "Already stripped",
            "Stripped",
            "DB cache hits",
            "Langfile hits",
        ],
    )
    def test_default_shows_always_visible_row(self, row: str) -> None:
        """Always-on rows still render with default Stats."""
        assert row in _render(Stats())

    def test_timestamps_active_shows_skipped_row(self) -> None:
        output = _render(Stats(timestamps_active=True))
        assert "Skipped (timestamp)" in output

    def test_dry_run_active_shows_dry_run_row(self) -> None:
        output = _render(Stats(dry_run_active=True))
        assert "Not remuxed (dry run)" in output

    def test_remote_db_active_shows_remote_db_hits_row(self) -> None:
        output = _render(Stats(remote_db_active=True))
        assert "Remote DB hits" in output

    def test_warnings_row_shown_only_when_warnings_present(self) -> None:
        stats = Stats()
        stats.record_warning(Path("/x.mkv"), "weird")
        output = _render(stats)
        assert "Warnings" in output

    def test_errors_row_shown_only_when_errors_present(self) -> None:
        stats = Stats()
        stats.record_error(Path("/x.mkv"), "boom")
        output = _render(stats)
        assert "Errors" in output
