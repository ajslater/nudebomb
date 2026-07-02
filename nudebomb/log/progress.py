"""Rich Progress bar with a streaming per-file char column."""

from __future__ import annotations

import threading
from collections import defaultdict, deque
from contextlib import contextmanager
from typing import TYPE_CHECKING, Final

from rich.markup import escape
from rich.progress import (
    MofNCompleteColumn,
    Progress,
    ProgressColumn,
    SpinnerColumn,
    TaskID,
    TextColumn,
    TimeElapsedColumn,
)
from rich.text import Text
from typing_extensions import Self, override

from nudebomb.log.styles import MARKS

if TYPE_CHECKING:
    from collections.abc import Callable, Generator
    from types import TracebackType

    from rich.console import Console
    from rich.progress import Task

__all__ = (
    "CharStreamColumn",
    "ProgressContext",
    "make_progress",
)


# Marks that count as a finished file and advance the bar.
_FILE_MARKS: Final = frozenset(
    {
        "ignored",
        "skipped_timestamp",
        "already_stripped",
        "stripped",
        "dry_run",
        "error",
    }
)

# The main bar's description; also the floor for sub-task description
# width so the description column never shrinks below the main row.
_MAIN_DESCRIPTION: Final = "Stripping MKVs"

# Width of the fixed columns besides the description: spinner(~2) +
# counts(~12) + time(~12) + inter-column spaces.
_FIXED_COLUMNS_WIDTH: Final = 32


class CharStreamColumn(ProgressColumn):
    """A column that shows the most-recent action chars as a streaming Text."""

    def __init__(self, max_width: int = 40) -> None:
        """Initialize the deque ring per task."""
        super().__init__()
        self._max_width = max_width
        self._streams: dict[int, deque[tuple[str, str]]] = defaultdict(
            lambda: deque(maxlen=self._max_width)
        )
        self._lock = threading.Lock()

    def push(self, task_id: int, char: str, style: str) -> None:
        """Append a styled char to ``task_id``'s ring."""
        with self._lock:
            self._streams[task_id].append((char, style))

    @override
    def render(self, task: Task) -> Text:
        """Render the ring for ``task`` as a Rich Text."""
        text = Text()
        with self._lock:
            stream = list(self._streams.get(task.id, ()))
        for char, style in stream:
            text.append(char, style=style)
        return text


class ProgressContext:
    """
    Owns the Progress and the single TaskID; provides mark_* helpers.

    When ``enabled=False`` (no TTY, ``--quiet``, or unit tests) every
    mark_*/__enter__/__exit__ is a no-op so callers can hold a
    ProgressContext unconditionally.
    """

    def __init__(
        self,
        progress: Progress | None = None,
        char_column: CharStreamColumn | None = None,
        task_id: TaskID | None = None,
        *,
        enabled: bool = False,
        max_description: int = len(_MAIN_DESCRIPTION),
    ) -> None:
        """Initialize."""
        self._progress = progress
        self._char_column = char_column
        self._task_id: TaskID | None = task_id
        self._enabled = enabled
        self._max_description = max_description

    def __enter__(self) -> Self:
        """Enter the underlying live progress region (no-op when disabled)."""
        if self._enabled and self._progress is not None:
            self._progress.__enter__()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Exit the underlying live progress region (no-op when disabled)."""
        if self._enabled and self._progress is not None:
            self._progress.__exit__(exc_type, exc_val, exc_tb)

    def _mark(self, kind: str) -> None:
        if (
            not self._enabled
            or self._progress is None
            or self._char_column is None
            or self._task_id is None
        ):
            return
        mark = MARKS[kind]
        self._char_column.push(int(self._task_id), mark.char, mark.style)
        if kind in _FILE_MARKS:
            self._progress.advance(self._task_id, 1)

    def mark_ignored(self) -> None:
        """Mark a file as ignored / skipped."""
        self._mark("ignored")

    def mark_skipped_timestamp(self) -> None:
        """Mark a file as skipped by timestamp."""
        self._mark("skipped_timestamp")

    def mark_already_stripped(self) -> None:
        """Mark a file as already stripped (no work needed)."""
        self._mark("already_stripped")

    def mark_stripped(self) -> None:
        """Mark a file as successfully stripped."""
        self._mark("stripped")

    def mark_dry_run(self) -> None:
        """Mark a file as would-have-been-stripped (dry-run)."""
        self._mark("dry_run")

    def mark_warning(self) -> None:
        """Mark a non-fatal issue (no bar advance)."""
        self._mark("warning")

    def mark_error(self) -> None:
        """Mark a fatal error processing a file."""
        self._mark("error")

    def mark_lookup_hit(self) -> None:
        """Mark a remote DB lookup hit (no bar advance)."""
        self._mark("lookup_hit")

    def mark_lookup_no_result(self) -> None:
        """Mark a remote DB lookup with no result (no bar advance)."""
        self._mark("lookup_no_result")

    def mark_lookup_rate_limited(self) -> None:
        """Mark a remote DB lookup that was rate-limited (no bar advance)."""
        self._mark("lookup_rate_limited")

    def mark_lookup_error(self) -> None:
        """Mark a remote DB lookup error (no bar advance)."""
        self._mark("lookup_error")

    @contextmanager
    def file_subtask(
        self, description: str
    ) -> Generator[Callable[[int], None], None, None]:
        """
        Yield a callable for updating a transient per-file sub-task.

        The sub-task lives inside the same Live region as the main bar,
        so per-file progress (e.g. mkvmerge percentage) renders beneath
        it without breaking the in-place redraw, and disappears on exit.
        When the ProgressContext is disabled, yields a no-op.
        """
        if not self._enabled or self._progress is None:
            yield _noop_update
            return
        # Capture in a local so the closure and the ``finally`` block
        # see a non-None Progress without re-narrowing.
        progress = self._progress
        # Truncate so the shared description column can't outgrow the
        # main row's budget (long release-style filenames would squeeze
        # the char stream and counts to zero width), and escape because
        # TextColumn parses descriptions as markup — filename bracket
        # tags would vanish or raise MarkupError mid-render.
        if len(description) > self._max_description:
            description = description[: self._max_description - 1] + "…"
        task_id = progress.add_task(escape(description), total=100)
        try:

            def _update(pct: int) -> None:
                progress.update(task_id, completed=pct)

            yield _update
        finally:
            progress.remove_task(task_id)


def _noop_update(_pct: int) -> None:
    """No-op fallback for `file_subtask` when progress is disabled."""


def make_progress(
    total: int,
    console: Console,
    *,
    enabled: bool = True,
) -> ProgressContext:
    """Build a ProgressContext for ``total`` files, or a no-op if disabled."""
    if not enabled or not console.is_terminal:
        return ProgressContext(enabled=False)

    # Size the streaming-char column so the whole bar fits on one line.
    # If the bar wraps, Rich's Live region flips into multi-line mode
    # and emits `\n` per refresh — which scrolls each frame past instead
    # of redrawing in place.
    #
    # Reserve room for the fixed columns plus the main description.
    # Cap the stream at 40 on very wide terminals.
    reserved = _FIXED_COLUMNS_WIDTH + len(_MAIN_DESCRIPTION)
    char_width = max(8, min(40, console.width - reserved))
    # Whatever width remains after the fixed columns and the char stream
    # is the budget for per-file sub-task descriptions; never below the
    # main description's own width.
    max_description = max(
        len(_MAIN_DESCRIPTION),
        console.width - _FIXED_COLUMNS_WIDTH - char_width,
    )
    char_column = CharStreamColumn(max_width=char_width)
    progress = Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        char_column,
        MofNCompleteColumn(),
        TimeElapsedColumn(),
        console=console,
        transient=False,
    )
    task_id = progress.add_task(_MAIN_DESCRIPTION, total=total)
    return ProgressContext(
        progress,
        char_column,
        task_id,
        enabled=True,
        max_description=max_description,
    )
