"""Tests for logging setup and verbosity levels."""

from loguru import logger

from nudebomb.log import console, setup

__all__ = ()


def test_quiet_still_emits_errors():
    """-q (verbose=0) must not silently drop ERROR output."""
    setup(0)
    with console.capture() as capture:
        logger.error("boom-error")
        logger.warning("hidden-warning")
    out = capture.get()
    assert "boom-error" in out
    assert "hidden-warning" not in out


def test_default_level_shows_warnings_hides_info():
    setup(1)
    with console.capture() as capture:
        logger.warning("visible-warning")
        logger.info("hidden-info")
    out = capture.get()
    assert "visible-warning" in out
    assert "hidden-info" not in out


def test_sink_renders_bracket_tags_literally():
    """Release-group tags in paths must not parse as Rich markup."""
    setup(1)
    with console.capture() as capture:
        logger.warning("opened /m/Movie [x265] [YTS.MX].mkv")
    assert "[x265]" in capture.get()


def test_sink_survives_closing_tag_text():
    """A [/...]-shaped substring must not raise MarkupError."""
    setup(1)
    with console.capture() as capture:
        logger.error("bad path /m/dir[/sub].mkv")
    assert "dir[/sub].mkv" in capture.get()
