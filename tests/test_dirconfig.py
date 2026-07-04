"""Tests for per-directory ``.nudebomb.yaml`` discovery and layering."""

import os
from pathlib import Path

import pytest

from nudebomb.cli import get_arguments
from nudebomb.config import NudebombConfig, NudebombSettings
from nudebomb.dirconfig import DirConfig
from nudebomb.log.summary import Stats

__all__ = ()


@pytest.fixture(autouse=True)
def _isolate_config(monkeypatch, tmp_path):
    """Point confuse at an empty config dir and scrub nudebomb env vars."""
    for key in list(os.environ):
        if key.startswith("NUDEBOMB"):
            monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("NUDEBOMBDIR", str(tmp_path / "config"))


def _dc(
    media: Path, *extra_argv: str, stats: Stats | None = None
) -> tuple[DirConfig, NudebombSettings]:
    """Build a DirConfig and the run-wide settings for a media tree."""
    media.mkdir(parents=True, exist_ok=True)
    argv = ("nudebomb", "-l", "eng", *extra_argv, str(media))
    args = get_arguments(argv)
    nudebomb_config = NudebombConfig()
    global_settings = nudebomb_config.get_config(args)
    return DirConfig(nudebomb_config, args, global_settings, stats), global_settings


def _write(directory: Path, text: str) -> None:
    """Write a ``.nudebomb.yaml`` in ``directory``."""
    directory.mkdir(parents=True, exist_ok=True)
    (directory / ".nudebomb.yaml").write_text(text)


def test_no_config_returns_global_instance(tmp_path):
    """With no directory config, the run-wide settings are returned as-is."""
    media = tmp_path / "media"
    dirconfig, global_settings = _dc(media)
    assert dirconfig.get_settings(media, media) is global_settings


def test_directory_config_overrides_user_default(tmp_path):
    """A directory config beats the packaged/user default."""
    media = tmp_path / "media"
    dirconfig, _ = _dc(media)
    _write(media, "nudebomb:\n  title: false\n")
    assert dirconfig.get_settings(media, media).title is False


def test_deeper_directory_wins(tmp_path):
    """A deeper directory config overrides a shallower one."""
    media = tmp_path / "media"
    nested = media / "a" / "b"
    dirconfig, _ = _dc(media)
    _write(media, "nudebomb:\n  sub_languages: [eng]\n")
    _write(nested, "nudebomb:\n  sub_languages: [jpn]\n")

    deep = dirconfig.get_settings(media, nested).sub_languages or frozenset()
    shallow = dirconfig.get_settings(media, media).sub_languages or frozenset()

    assert "jpn" in deep
    assert "eng" not in deep
    assert "eng" in shallow
    assert "jpn" not in shallow


def test_boundary_stops_at_top_path(tmp_path):
    """A config above the CLI target root is never read."""
    media = tmp_path / "media"
    dirconfig, _ = _dc(media)
    # Sentinel above top_path — must be ignored.
    _write(tmp_path, "nudebomb:\n  title: false\n")
    assert dirconfig.get_settings(media, media).title is True


def test_cli_wins_over_directory_config(tmp_path):
    """CLI options override a directory config."""
    media = tmp_path / "media"
    dirconfig, global_settings = _dc(media, "-T")  # --no-title => title False
    assert global_settings.title is False
    _write(media, "nudebomb:\n  title: true\n")
    assert dirconfig.get_settings(media, media).title is False


def test_env_wins_over_directory_config(tmp_path, monkeypatch):
    """Environment variables override a directory config."""
    monkeypatch.setenv("NUDEBOMB_NUDEBOMB__TITLE", "False")
    media = tmp_path / "media"
    dirconfig, _ = _dc(media)
    _write(media, "nudebomb:\n  title: true\n")
    assert dirconfig.get_settings(media, media).title is False


def test_languages_replace_not_union(tmp_path):
    """A directory config's languages replace the inherited (user) value."""
    media = tmp_path / "media"
    media.mkdir(parents=True)
    # Inherited languages come from the user config (not the CLI, which would
    # otherwise win), so the directory config is free to replace them.
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "config.yaml").write_text("nudebomb:\n  languages: [eng]\n")
    args = get_arguments(("nudebomb", str(media)))
    nudebomb_config = NudebombConfig()
    global_settings = nudebomb_config.get_config(args)
    dirconfig = DirConfig(nudebomb_config, args, global_settings)
    _write(media, "nudebomb:\n  languages: [deu]\n")

    languages = dirconfig.get_settings(media, media).languages
    assert "deu" in languages
    assert "eng" not in languages


def test_full_schema_media_type(tmp_path):
    """Any schema key resolves per directory (full schema)."""
    media = tmp_path / "media"
    dirconfig, _ = _dc(media)
    _write(media, "nudebomb:\n  media_type: tv\n")
    assert dirconfig.get_settings(media, media).media_type == "tv"


def test_single_file_target_boundary(tmp_path):
    """A single-file target reads its own directory but nothing above it."""
    media = tmp_path / "media"
    show = media / "show"
    show.mkdir(parents=True)
    dirconfig, _ = _dc(media)
    _write(show, "nudebomb:\n  title: false\n")
    _write(media, "nudebomb:\n  subtitles: false\n")  # above the file's top_path

    # Target is the file media/show/ep.mkv → top_path is media/show.
    settings = dirconfig.get_settings(show, show)
    assert settings.title is False
    assert settings.subtitles is True  # media/ config is above top_path


def test_malformed_config_falls_back_and_records_error(tmp_path):
    """A broken directory config is isolated; siblings still resolve."""
    media = tmp_path / "media"
    stats = Stats(timestamps_active=False, dry_run_active=False, remote_db_active=False)
    dirconfig, global_settings = _dc(media, stats=stats)
    _write(media / "bad", "::: not: valid: [yaml\n")
    _write(media / "good", "nudebomb:\n  title: false\n")

    bad = dirconfig.get_settings(media, media / "bad")
    good = dirconfig.get_settings(media, media / "good")

    assert bad is global_settings  # fell back to run-wide settings
    assert good.title is False  # sibling unaffected
    assert stats.errors


def test_malformed_config_logged_once(tmp_path):
    """The same broken config is reported only once across siblings."""
    media = tmp_path / "media"
    stats = Stats(timestamps_active=False, dry_run_active=False, remote_db_active=False)
    dirconfig, _ = _dc(media, stats=stats)
    _write(media, "::: not: valid: [yaml\n")

    # Two descendant directories both re-read the broken media/ config.
    (media / "a").mkdir()
    (media / "b").mkdir()
    dirconfig.get_settings(media, media / "a")
    dirconfig.get_settings(media, media / "b")

    assert len(stats.errors) == 1


def test_settings_cached_per_directory(tmp_path):
    """Repeated resolution of a directory reuses the cached settings."""
    media = tmp_path / "media"
    dirconfig, _ = _dc(media)
    _write(media, "nudebomb:\n  title: false\n")
    first = dirconfig.get_settings(media, media)
    second = dirconfig.get_settings(media, media)
    assert first is second
