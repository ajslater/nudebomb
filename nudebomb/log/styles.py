"""
Centralized color / style / char definitions for nudebomb output.

Single source of truth for everything user-facing: the streaming-char
column on the progress bar, the loguru sink that writes log lines, the
end-of-run summary table, and the help-epilogue char-key legend.

Why centralize: the same outcome (e.g. "ignored file") should read the
same way on the bar, in the summary, and in the legend. Changing the
visual treatment of any event should require editing exactly one
place.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = (
    "LEVEL_STYLES",
    "LOOKUP_HIT_LEVEL",
    "MARKS",
    "Mark",
)


@dataclass(frozen=True, slots=True)
class Mark:
    """A single (char, Rich-style) pair for a per-event progress mark."""

    char: str
    style: str


# Custom loguru level for remote DB hits — sits at INFO numeric level
# but gets its own color so it pops next to neutral INFO lines.
LOOKUP_HIT_LEVEL: Final = "DBHIT"


# Per-event marks. Keys mirror the names used by `Stats` / `mark_*`
# helpers and the summary table rows.
#
# Style notes:
#  - We avoid Rich's `dim` (`\x1b[2m`) and the 16-color `bright_black`
#    extension (`\x1b[90m`) for the grey marks: some terminals render
#    `\x1b[2m` as literal escape text, and at least one Rich 15
#    environment renders `bright_black` with an unwanted faint prefix.
#    `grey50` resolves to a single 256-color code (`\x1b[38;5;244m`)
#    which renders cleanly everywhere.
#  - `bold` is used as emphasis where the original termcolor scheme had
#    `[bold]` (e.g. dry-run, timestamp-skipped).
MARKS: Final[Mapping[str, Mark]] = MappingProxyType(
    {
        # Per-file marks (advance the bar)
        "ignored": Mark(".", "grey50"),
        "skipped_timestamp": Mark(".", "bold bright_green"),
        "already_stripped": Mark(".", "green"),
        "stripped": Mark("*", "white"),
        "dry_run": Mark("*", "bold grey50"),
        "warning": Mark("!", "yellow"),
        "error": Mark("X", "bold red"),
        # Lookup marks (do not advance the bar)
        "lookup_hit": Mark("O", "cyan"),
        "lookup_no_result": Mark("x", "yellow"),
        "lookup_rate_limited": Mark("X", "yellow"),
        "lookup_error": Mark("X", "bold red"),
    }
)


def _style(key: str) -> str:
    return MARKS[key].style


# Loguru level → Rich style. Levels that correspond to a per-event mark
# share that mark's style so log lines and progress chars match.
LEVEL_STYLES: Final[Mapping[str, str]] = MappingProxyType(
    {
        "DEBUG": _style("ignored"),
        "INFO": _style("stripped"),
        LOOKUP_HIT_LEVEL: _style("lookup_hit"),
        "SUCCESS": _style("already_stripped"),
        "WARNING": _style("warning"),
        "ERROR": _style("error"),
    }
)
