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
