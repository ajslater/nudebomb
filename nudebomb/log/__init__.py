"""Loguru + Rich logging setup."""

from __future__ import annotations

import logging
from contextlib import suppress
from typing import TYPE_CHECKING, Final

from loguru import logger
from rich.console import Console
from typing_extensions import override

from nudebomb.log.styles import LEVEL_STYLES, LOOKUP_HIT_LEVEL

if TYPE_CHECKING:
    from loguru import Record

__all__ = ("LOOKUP_HIT_LEVEL", "console", "logger", "setup")

# Single Console for everything — both Rich Progress and the loguru sink
# share it so the live region and log lines stay in sync.
#
# `highlight=False` is critical: the default repr-highlighter would
# otherwise be applied to anything Rich re-prints internally, including
# the rendered ANSI strings produced by the live progress bar. On some
# installs that turns each `[` in `\x1b[Xm` sequences into a bold-styled
# bracket and leaves the leading `\x1b` as a stray byte, so the dots
# show up as literal `[2m[90m.[0m` text in the terminal.
console: Final[Console] = Console(highlight=False)

# verbose -> minimum loguru level to emit
_VERBOSE_LEVEL: Final = {
    0: "ERROR",
    1: "WARNING",
    2: "INFO",
}


def _verbose_to_level(verbose: int) -> str:
    if verbose <= 0:
        return "ERROR"
    return _VERBOSE_LEVEL.get(verbose, "DEBUG")


def _sink(message: object) -> None:
    """Write a loguru record to the shared Rich console."""
    record: Record = message.record  # pyright: ignore[reportAttributeAccessIssue], # ty: ignore[unresolved-attribute]
    level = record["level"].name
    style = LEVEL_STYLES.get(level, "white")
    text = record["message"]
    # markup=False: messages embed arbitrary paths and mkvmerge output;
    # bracketed release tags like [x265] would parse as Rich markup and
    # vanish, and a stray [/...] would raise MarkupError.
    console.print(text, style=style, markup=False, highlight=False, soft_wrap=True)


class _InterceptHandler(logging.Handler):
    """Forward stdlib `logging` records into loguru."""

    @override
    def emit(self, record: logging.LogRecord) -> None:
        """Re-log the record through loguru at the equivalent level."""
        try:
            level: str | int = logger.level(record.levelname).name
        except ValueError:
            # A stdlib level with no loguru equivalent; the numeric
            # value still routes to the right sink threshold.
            level = record.levelno
        logger.log(level, record.getMessage())


# Libraries that log through stdlib `logging` (treestamps, urllib3, …)
# would otherwise fall through to `logging.lastResort`, which prints
# uncolored text straight to stderr — bypassing the level styles and
# the shared console the progress bar redraws into.
_stdlib_handler: Final = _InterceptHandler()

_configured = False


def _intercept_stdlib(level: str) -> None:
    """Route stdlib `logging` through the loguru sink at ``level``."""
    root = logging.getLogger()
    # Add rather than replace: pytest's caplog and friends install their
    # own root handlers and must keep working.
    if _stdlib_handler not in root.handlers:
        root.addHandler(_stdlib_handler)
    # Root defaults to WARNING, which would drop INFO/DEBUG before the
    # sink ever sees them; the sink does the real verbosity filtering.
    root.setLevel(level)


def setup(verbose: int) -> None:
    """Configure loguru for the given verbosity. Idempotent."""
    global _configured  # noqa: PLW0603
    if not _configured:
        # Already registered raises ValueError (e.g. test re-entry).
        with suppress(ValueError):
            logger.level(LOOKUP_HIT_LEVEL, no=22, color="<cyan>")
        _configured = True

    logger.remove()
    # Even -q keeps a sink registered: _verbose_to_level maps verbose<=0
    # to ERROR so failures are never silently dropped.
    level = _verbose_to_level(verbose)
    logger.add(
        _sink,
        level=level,
        format="{message}",
    )
    _intercept_stdlib(level)
