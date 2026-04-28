"""Bundles Stats + ProgressContext so workers have a single sink."""

from __future__ import annotations

from dataclasses import dataclass, field

from nudebomb.log.progress import ProgressContext
from nudebomb.log.summary import Stats

__all__ = ("Reporter",)


@dataclass(slots=True)
class Reporter:
    """
    Aggregates run-level reporting sinks for workers.

    Defaults give a no-op progress and a detached Stats instance, so
    callers (especially in tests) can construct a lookup without wiring
    the full run plumbing.
    """

    stats: Stats = field(default_factory=Stats)
    progress: ProgressContext = field(default_factory=ProgressContext)
