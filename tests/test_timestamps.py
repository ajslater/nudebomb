"""Tests for directory-config control of timestamp tracking."""

import os
from pathlib import Path

import pytest

from nudebomb.cli import get_arguments
from nudebomb.config import NudebombConfig
from nudebomb.walk import Walk

__all__ = ()


@pytest.fixture(autouse=True)
def _isolate_config(monkeypatch, tmp_path):
    """Point confuse at an empty config dir and scrub nudebomb env vars."""
    for key in list(os.environ):
        if key.startswith("NUDEBOMB"):
            monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("NUDEBOMBDIR", str(tmp_path / "config"))


def _walk(media: Path, *extra_argv: str) -> Walk:
    media.mkdir(parents=True, exist_ok=True)
    argv = ("nudebomb", "-r", *extra_argv, "-l", "eng", str(media))
    args = get_arguments(argv)
    config = NudebombConfig().get_config(args)
    return Walk(config, args)


def test_dir_config_enables_timestamps_when_global_off(tmp_path):
    """A directory config turns timestamps on even with the global flag off."""
    media = tmp_path / "media"
    movies = media / "Movies"
    movies.mkdir(parents=True)
    (movies / ".nudebomb.yaml").write_text("nudebomb:\n  timestamps: true\n")
    other = media / "Other"
    other.mkdir()

    walk = _walk(media)

    assert walk._config.timestamps is False  # run-wide flag is off
    assert walk._timestamps_enabled() is True  # a directory turns it on
    walk._read_timestamps()
    assert walk._timestamps is not None  # store was built
    assert walk._dir_timestamps(media, movies) is True
    assert walk._dir_timestamps(media, other) is False  # sibling stays off


def test_no_timestamps_anywhere_builds_no_store(tmp_path):
    """With no global flag and no directory config, no store is built."""
    media = tmp_path / "media"

    walk = _walk(media)

    assert walk._timestamps_enabled() is False
    walk._read_timestamps()
    assert walk._timestamps is None


def test_dir_config_can_disable_timestamps_from_user_config(tmp_path):
    """A directory config can turn timestamps off when the user config has it on."""
    media = tmp_path / "media"
    quiet = media / "Quiet"
    quiet.mkdir(parents=True)
    (quiet / ".nudebomb.yaml").write_text("nudebomb:\n  timestamps: false\n")
    # Global timestamps on via the user config (not CLI -t, which would win
    # over the directory config).
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "config.yaml").write_text("nudebomb:\n  timestamps: true\n")

    walk = _walk(media)  # no -t on the CLI

    assert walk._config.timestamps is True  # from the user config
    walk._read_timestamps()
    assert walk._timestamps is not None
    assert walk._dir_timestamps(media, media) is True  # inherits user-config on
    assert walk._dir_timestamps(media, quiet) is False  # dir override wins
