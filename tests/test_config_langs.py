"""Tests for the "Config file langs" summary metric."""

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


class _StubMKV:
    """Stand in for MKVFile so strip_path needs no mkvmerge."""

    def __init__(self, *_args) -> None:
        pass

    def update_languages(self, _languages) -> None:
        pass

    def remove_tracks(self) -> bool:
        return True


def _walk(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Walk, Path]:
    monkeypatch.setattr("nudebomb.walk.MKVFile", _StubMKV)
    # Global languages via the user config so the directory config's [jpn]
    # is not shadowed by a CLI --languages.
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "config.yaml").write_text("nudebomb:\n  languages: [eng]\n")
    media = tmp_path / "media"
    anime = media / "anime"
    anime.mkdir(parents=True)
    (anime / ".nudebomb.yaml").write_text("nudebomb:\n  languages: [jpn]\n")
    (anime / "ep.mkv").write_bytes(b"x")
    plain = media / "plain"
    plain.mkdir()
    (plain / "movie.mkv").write_bytes(b"x")
    args = get_arguments(("nudebomb", "-r", str(media)))
    config = NudebombConfig().get_config(args)
    return Walk(config, args), media


def test_hit_when_dir_config_changes_languages(tmp_path, monkeypatch):
    """A directory config that changes the keep-set counts the file."""
    walk, media = _walk(tmp_path, monkeypatch)
    walk.strip_path(media, media / "anime" / "ep.mkv")
    assert walk._stats.config_lang_hits == 1


def test_no_hit_without_dir_config(tmp_path, monkeypatch):
    """A file with no directory-config language override is not counted."""
    walk, media = _walk(tmp_path, monkeypatch)
    walk.strip_path(media, media / "plain" / "movie.mkv")
    assert walk._stats.config_lang_hits == 0
