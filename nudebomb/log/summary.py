"""End-of-run summary statistics and rendering."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from rich.table import Table

if TYPE_CHECKING:
    from pathlib import Path

    from rich.console import Console

__all__ = ("Stats", "render")


@dataclass(slots=True)
class Stats:
    """Thread-safe counters and itemized lists for the end-of-run summary."""

    ignored: int = 0
    skipped_timestamp: int = 0
    already_stripped: int = 0

    stripped: list[Path] = field(default_factory=list)
    dry_run: list[Path] = field(default_factory=list)
    warnings: list[tuple[Path | None, str]] = field(default_factory=list)
    errors: list[tuple[Path | None, str]] = field(default_factory=list)

    db_cache_hits: int = 0
    db_remote_hits: int = 0
    langfile_hits: int = 0

    db_no_results: list[str] = field(default_factory=list)
    db_remote_errors: list[str] = field(default_factory=list)

    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def record_ignored(self) -> None:
        """Increment the ignored counter."""
        with self._lock:
            self.ignored += 1

    def record_skipped_timestamp(self) -> None:
        """Increment the timestamp-skipped counter."""
        with self._lock:
            self.skipped_timestamp += 1

    def record_already_stripped(self) -> None:
        """Increment the already-stripped counter."""
        with self._lock:
            self.already_stripped += 1

    def record_stripped(self, path: Path) -> None:
        """Append a successfully-stripped file path."""
        with self._lock:
            self.stripped.append(path)

    def record_dry_run(self, path: Path) -> None:
        """Append a path that would have been stripped (dry-run)."""
        with self._lock:
            self.dry_run.append(path)

    def record_warning(self, path: Path | None, message: str) -> None:
        """Append a warning tied to a file."""
        with self._lock:
            self.warnings.append((path, message))

    def record_error(self, path: Path | None, message: str) -> None:
        """Append an error tied to a file."""
        with self._lock:
            self.errors.append((path, message))

    def record_db_cache_hit(self) -> None:
        """Increment the DB cache-hit counter."""
        with self._lock:
            self.db_cache_hits += 1

    def record_db_remote_hit(self) -> None:
        """Increment the remote-DB hit counter."""
        with self._lock:
            self.db_remote_hits += 1

    def record_langfile_hit(self) -> None:
        """Increment the langfile-hit counter."""
        with self._lock:
            self.langfile_hits += 1

    def record_db_no_result(self, message: str) -> None:
        """Append a no-result message to the DB no-results list."""
        with self._lock:
            self.db_no_results.append(message)

    def record_db_remote_error(self, message: str) -> None:
        """Append an error message to the remote-DB errors list."""
        with self._lock:
            self.db_remote_errors.append(message)


def _counts_table(stats: Stats) -> Table:
    """
    Build the Counts table for the summary.

    Row styles match the per-event color scheme used by the loguru sink
    and the progress bar's CharStreamColumn so the same outcome reads
    the same way everywhere.
    """
    table = Table(title="Summary", show_header=False, title_style="bold")
    table.add_column("Metric")
    table.add_column("Count", justify="right")
    table.add_row("Ignored", str(stats.ignored), style="grey50")
    table.add_row(
        "Skipped (timestamp)",
        str(stats.skipped_timestamp),
        style="bold bright_green",
    )
    table.add_row("Already stripped", str(stats.already_stripped), style="green")
    table.add_row("Stripped", str(len(stats.stripped)), style="white")
    table.add_row("Not remuxed (dry run)", str(len(stats.dry_run)), style="bold grey50")
    table.add_row("Warnings", str(len(stats.warnings)), style="yellow")
    table.add_row("Errors", str(len(stats.errors)), style="bold red")
    table.add_row("DB cache hits", str(stats.db_cache_hits), style="cyan")
    table.add_row("Remote DB hits", str(stats.db_remote_hits), style="cyan")
    table.add_row("Langfile hits", str(stats.langfile_hits), style="cyan")
    return table


def _print_paths(
    console: Console, header: str, paths: list[Path], style: str = ""
) -> None:
    if not paths:
        return
    console.print(f"[bold]{header}:[/bold]")
    for path in paths:
        line = f"  - {path}"
        console.print(f"[{style}]{line}[/{style}]" if style else line, highlight=False)


def _print_pairs(
    console: Console,
    header: str,
    pairs: list[tuple[Path | None, str]],
    style: str = "",
) -> None:
    if not pairs:
        return
    console.print(f"[bold]{header}:[/bold]")
    for path, message in pairs:
        line = f"  - {path}: {message}" if path else f"  - {message}"
        console.print(f"[{style}]{line}[/{style}]" if style else line, highlight=False)


def _print_messages(
    console: Console, header: str, messages: list[str], style: str = ""
) -> None:
    if not messages:
        return
    console.print(f"[bold]{header}:[/bold]")
    for message in messages:
        line = f"  - {message}"
        console.print(f"[{style}]{line}[/{style}]" if style else line, highlight=False)


def render(stats: Stats, console: Console) -> None:
    """Print the summary to the given Rich console."""
    console.print(_counts_table(stats))
    _print_paths(console, "Stripped tracks", stats.stripped, "green")
    _print_paths(console, "Not remuxed (dry run)", stats.dry_run, "bold grey50")
    _print_pairs(console, "Warnings", stats.warnings, "yellow")
    _print_pairs(console, "Errors", stats.errors, "bold red")
    _print_messages(console, "DB lookups with no result", stats.db_no_results, "yellow")
    _print_messages(console, "Remote DB errors", stats.db_remote_errors, "bold red")
