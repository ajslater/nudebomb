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
from enum import StrEnum, auto
from types import MappingProxyType
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = (
    "LEVEL_STYLES",
    "LOOKUP_HIT_LEVEL",
    "MARKS",
    "Mark",
    "MarkKind",
)


@dataclass(frozen=True, slots=True)
class Mark:
    """A single (char, Rich-style) pair for a per-event progress mark."""

    char: str
    style: str


class MarkKind(StrEnum):
    """Per-event progress mark kinds, the keys of :data:`MARKS`."""

    # Per-file marks (all but WARNING advance the bar)
    IGNORED = auto()
    SKIPPED_TIMESTAMP = auto()
    ALREADY_STRIPPED = auto()
    STRIPPED = auto()
    DRY_RUN = auto()
    WARNING = auto()
    ERROR = auto()
    # Lookup marks (do not advance the bar)
    LOOKUP_HIT = auto()
    LOOKUP_NO_RESULT = auto()
    LOOKUP_RATE_LIMITED = auto()
    LOOKUP_ERROR = auto()


# Custom loguru level for remote DB hits — sits at INFO numeric level
# but gets its own color so it pops next to neutral INFO lines.
LOOKUP_HIT_LEVEL: Final = "DBHIT"


# Per-event marks. Kinds mirror the names used by `Stats` / `mark_*`
# helpers and the summary table rows.
#
# Style notes:
#  - `bold` is used as emphasis where the original termcolor scheme had
#    `[bold]` (e.g. dry-run, timestamp-skipped).
MARKS: Final[Mapping[MarkKind, Mark]] = MappingProxyType(
    {
        MarkKind.IGNORED: Mark(".", "dim"),
        MarkKind.SKIPPED_TIMESTAMP: Mark(".", "dim green"),
        MarkKind.ALREADY_STRIPPED: Mark(".", "green"),
        MarkKind.STRIPPED: Mark("*", "white"),
        MarkKind.DRY_RUN: Mark("*", "bold grey50"),
        MarkKind.WARNING: Mark("!", "yellow"),
        MarkKind.ERROR: Mark("X", "bold red"),
        MarkKind.LOOKUP_HIT: Mark("O", "cyan"),
        MarkKind.LOOKUP_NO_RESULT: Mark("x", "yellow"),
        MarkKind.LOOKUP_RATE_LIMITED: Mark("X", "yellow"),
        MarkKind.LOOKUP_ERROR: Mark("X", "bold red"),
    }
)


def _style(kind: MarkKind) -> str:
    return MARKS[kind].style


# Loguru level → Rich style. Levels that correspond to a per-event mark
# share that mark's style so log lines and progress chars match.
LEVEL_STYLES: Final[Mapping[str, str]] = MappingProxyType(
    {
        "DEBUG": _style(MarkKind.IGNORED),
        "INFO": _style(MarkKind.STRIPPED),
        LOOKUP_HIT_LEVEL: _style(MarkKind.LOOKUP_HIT),
        "SUCCESS": _style(MarkKind.ALREADY_STRIPPED),
        "WARNING": _style(MarkKind.WARNING),
        "ERROR": _style(MarkKind.ERROR),
    }
)
