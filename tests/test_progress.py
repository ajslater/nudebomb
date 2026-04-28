"""Tests for the progress module."""

import io

from rich.console import Console
from rich.progress import Progress, Task

from nudebomb.log.progress import CharStreamColumn, ProgressContext, make_progress

__all__ = ()


class TestCharStreamColumn:
    """CharStreamColumn pushes and renders styled chars per task."""

    def test_push_then_render(self) -> None:
        column = CharStreamColumn()
        column.push(0, ".", "dim")
        column.push(0, "*", "white")
        column.push(0, "X", "bold red")

        # Build a stub Task — only `id` is read by render().
        task = object.__new__(Task)
        task.id = 0  # pyright: ignore[reportAttributeAccessIssue]
        text = column.render(task)
        assert str(text) == ".*X"

    def test_ring_buffer_caps(self) -> None:
        column = CharStreamColumn(max_width=3)
        for char in "abcdefg":
            column.push(0, char, "white")
        task = object.__new__(Task)
        task.id = 0  # pyright: ignore[reportAttributeAccessIssue]
        # Only the last 3 chars survive.
        assert str(column.render(task)) == "efg"


class TestProgressContext:
    """ProgressContext is a no-op when disabled and advances when enabled."""

    def test_disabled_marks_are_noops(self) -> None:
        ctx = ProgressContext(enabled=False)
        with ctx:
            ctx.mark_ignored()
            ctx.mark_stripped()
            ctx.mark_lookup_hit()
        # No exception, no state.

    def test_enabled_marks_advance(self) -> None:
        column = CharStreamColumn()
        progress = Progress()
        task_id = progress.add_task("test", total=10)
        ctx = ProgressContext(progress, column, task_id, enabled=True)

        ctx.mark_stripped()
        ctx.mark_already_stripped()
        ctx.mark_lookup_hit()  # does NOT advance

        # Two file marks → completed=2
        task = next(t for t in progress.tasks if t.id == task_id)
        assert task.completed == 2  # noqa: PLR2004

        # Char stream has all three pushes.
        rendered = str(column.render(task))
        assert len(rendered) == 3  # noqa: PLR2004


class TestMakeProgress:
    """make_progress disables itself in a non-TTY context."""

    def test_non_tty_returns_disabled(self) -> None:
        buffer = io.StringIO()
        console = Console(file=buffer, force_terminal=False)
        ctx = make_progress(10, console, enabled=True)
        # Disabled context still supports the protocol.
        with ctx:
            ctx.mark_ignored()
        # Non-TTY produces no progress output.
        assert buffer.getvalue() == ""

    def test_explicit_disabled_returns_noop(self) -> None:
        buffer = io.StringIO()
        console = Console(file=buffer, force_terminal=True)
        ctx = make_progress(10, console, enabled=False)
        with ctx:
            ctx.mark_ignored()
        assert buffer.getvalue() == ""
