"""Tests for logging setup and verbosity levels."""

import logging

from loguru import logger

from nudebomb.log import console, setup
from nudebomb.log.styles import LEVEL_STYLES

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


def test_stdlib_warning_is_styled_like_a_loguru_warning(monkeypatch):
    """Treestamps logs via stdlib logging; it must not bypass the sink."""
    setup(1)
    # Assert on the style handed to the console: a captured non-terminal
    # console renders no ANSI, so the raw output can't prove the color.
    printed: list[tuple[str, str]] = []
    monkeypatch.setattr(
        console,
        "print",
        lambda text, **kwargs: printed.append((text, kwargs["style"])),
    )
    logging.getLogger("treestamps.tree.load").warning(
        "Not loading timestamps from %s into tree %s: config mismatch for: %s",
        "/m/.nudebomb_treestamps.yaml",
        "/m",
        ".nudebomb.yaml contents",
    )
    message = (
        "Not loading timestamps from /m/.nudebomb_treestamps.yaml into tree /m: "
        "config mismatch for: .nudebomb.yaml contents"
    )
    assert printed == [(message, LEVEL_STYLES["WARNING"])]


def test_stdlib_verbosity_follows_setup():
    """Stdlib INFO records stay hidden at the default level."""
    setup(1)
    with console.capture() as capture:
        logging.getLogger("treestamps.tree.load").info("hidden-stdlib-info")
    assert "hidden-stdlib-info" not in capture.get()

    setup(2)
    with console.capture() as capture:
        logging.getLogger("treestamps.tree.load").info("visible-stdlib-info")
    assert "visible-stdlib-info" in capture.get()
