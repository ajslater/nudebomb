"""
Centralized color / style / char definitions for nudebomb output.

Single source of truth for everything user-facing: the streaming-char
column on the progress bar, the loguru sink that writes log lines, the
end-of-run summary table, the help-epilogue char-key legend, and the
``nudebomb doctor`` report.

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
    "DOCTOR_COMMAND",
    "DOCTOR_DETAIL_STYLES",
    "DOCTOR_HINT",
    "DOCTOR_LABEL",
    "DOCTOR_NAME",
    "DOCTOR_PATH",
    "DOCTOR_SECTION",
    "DOCTOR_STATUS_MARKS",
    "DOCTOR_SUMMARY",
    "DOCTOR_VERSION",
    "LEVEL_STYLES",
    "LOOKUP_HIT_LEVEL",
    "MARKS",
    "DoctorStatus",
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


class DoctorStatus(StrEnum):
    """Outcome of one ``nudebomb doctor`` check."""

    OK = auto()
    WARN = auto()
    FAIL = auto()
    SKIP = auto()


# Doctor status tags reuse the per-file mark styles, so "ok" is the same
# green as "already stripped" and "skip" the same dim as "ignored". The
# char is the tag text.
DOCTOR_STATUS_MARKS: Final[Mapping[DoctorStatus, Mark]] = MappingProxyType(
    {
        DoctorStatus.OK: Mark("ok", _style(MarkKind.ALREADY_STRIPPED)),
        DoctorStatus.WARN: Mark("WARN", _style(MarkKind.WARNING)),
        DoctorStatus.FAIL: Mark("FAIL", _style(MarkKind.ERROR)),
        DoctorStatus.SKIP: Mark("skip", _style(MarkKind.IGNORED)),
    }
)
# Detail text after the tag. A failure's detail is plain red rather than
# the tag's bold red so the tag stays the loudest thing on the line.
DOCTOR_DETAIL_STYLES: Final[Mapping[DoctorStatus, str]] = MappingProxyType(
    {
        DoctorStatus.OK: "",
        DoctorStatus.WARN: DOCTOR_STATUS_MARKS[DoctorStatus.WARN].style,
        DoctorStatus.FAIL: "red",
        DoctorStatus.SKIP: DOCTOR_STATUS_MARKS[DoctorStatus.SKIP].style,
    }
)
DOCTOR_SECTION: Final = "bold yellow"
DOCTOR_NAME: Final = "bold cyan"
DOCTOR_LABEL: Final = "cyan"
# picopt uses `bold black`, which nearly vanishes on dark themes.
DOCTOR_VERSION: Final = "bold"
# picopt uses `dim white`, which washes out on light themes.
DOCTOR_PATH: Final = "dim"
DOCTOR_HINT: Final = "dim"
# The `argparse.example` color in the help formatter.
DOCTOR_COMMAND: Final = "green"
DOCTOR_SUMMARY: Final = "bold"
