"""Tests for the nudebomb doctor report rendering."""

from io import StringIO

from rich.console import Console
from rich.style import Style
from rich.text import Text

from nudebomb.doctor import FAIL, OK, WARN, CheckResult, render

__all__ = ()


class TestRender:
    SECTIONS = (
        (
            "Tools",
            (
                CheckResult(
                    "mkvmerge", OK, "('x') 64-bit", version="v1.0", path="/bin/[x265]"
                ),
                CheckResult("other", FAIL, "boom [/bold]", hint="brew install x"),
            ),
        ),
        ("Online lookup", (CheckResult("TMDB", WARN, "rate limited"),)),
    )

    @staticmethod
    def _styles(console: Console) -> dict[str, Style | None]:
        """Map each recorded segment's text to its style."""
        return {
            segment.text: segment.style
            for segment in console._record_buffer
            if segment.text.strip()
        }

    def test_styles(self) -> None:
        console = Console(record=True, force_terminal=True, width=100)
        render(self.SECTIONS, (), console)
        styles = self._styles(console)
        assert styles["FAIL"] == Style.parse("bold red")
        assert styles["v1.0"] == Style.parse("bold")
        assert styles["[/bin/[x265]]"] == Style.parse("dim")
        assert styles["boom [/bold]"] == Style.parse("red")
        text = console.export_text()
        assert "v1.0 ('x') 64-bit [/bin/[x265]]" in text
        assert "install: brew install x" in text
        assert "Summary: 1 ok, 1 warning, 1 failed, 0 skipped." in text

    def test_summary_plural(self) -> None:
        console = Console(record=True, width=100)
        warnings = ("w", tuple(CheckResult(n, WARN, "") for n in "ab"))
        render((warnings,), (), console)
        assert "0 ok, 2 warnings, 0 failed" in console.export_text()

    def test_details_align_across_sections(self) -> None:
        console = Console(record=True, width=100)
        environment = [("nudebomb", Text("1.0"))]
        render(self.SECTIONS, environment, console)
        lines = console.export_text().splitlines()
        tmdb = next(line for line in lines if "TMDB" in line)
        env = next(line for line in lines if line.startswith("  nudebomb"))
        assert tmdb.index("rate limited") == env.index("1.0")

    def test_plain_when_not_a_terminal(self) -> None:
        out = StringIO()
        render(self.SECTIONS, (), Console(file=out, width=100))
        assert "\x1b" not in out.getvalue()
        assert "FAIL" in out.getvalue()

    def test_problems_only(self) -> None:
        console = Console(record=True, width=100)
        render(self.SECTIONS, [("x", Text("y"))], console, problems_only=False)
        full = console.export_text()
        render(self.SECTIONS, (), console, problems_only=True)
        problems = console.export_text()
        assert "mkvmerge" in full
        assert "mkvmerge" not in problems
        assert "other" in problems
