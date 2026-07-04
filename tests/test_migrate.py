"""Tests for migrating deprecated langfiles to .nudebomb.yaml."""

import os
from pathlib import Path

import pytest
from ruamel.yaml import YAML

from nudebomb.cli import get_arguments
from nudebomb.config import DirConfig, LangfileMigrator, LangFiles, NudebombConfig
from nudebomb.log.summary import Stats
from nudebomb.walk import Walk

__all__ = ()


def yaml_load(path: Path) -> dict:
    """Load a YAML file for assertions."""
    return YAML().load(path.read_text())


@pytest.fixture(autouse=True)
def _isolate_config(monkeypatch, tmp_path):
    """Point confuse at an empty config dir and scrub nudebomb env vars."""
    for key in list(os.environ):
        if key.startswith("NUDEBOMB"):
            monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("NUDEBOMBDIR", str(tmp_path / "config"))


def _migrator(media: Path, *extra_argv: str, stats: Stats | None = None):
    """Build a LangfileMigrator for a media tree."""
    media.mkdir(parents=True, exist_ok=True)
    argv = ("nudebomb", "-l", "eng", *extra_argv, str(media))
    args = get_arguments(argv)
    nudebomb_config = NudebombConfig()
    config = nudebomb_config.get_config(args)
    langfiles = LangFiles(config, stats=stats)
    dirconfig = DirConfig(nudebomb_config, args, config, stats)
    return LangfileMigrator(config, langfiles, dirconfig, stats)


def _langs(directory: Path) -> set[str]:
    return set(yaml_load(directory / ".nudebomb.yaml")["nudebomb"]["languages"])


def test_migrate_creates_config_and_deletes_langfile(tmp_path):
    """A langfile becomes a .nudebomb.yaml preserving the effective keep-set."""
    media = tmp_path / "media"
    anime = media / "anime"
    anime.mkdir(parents=True)
    (anime / ".lang").write_text("jpn\n")

    _migrator(media).migrate_dir(media, anime)

    assert not (anime / ".lang").exists()
    # Preserves today's set: global eng (+und) plus the langfile's jpn.
    assert _langs(anime) == {"eng", "jpn", "und"}


def test_migrate_merges_into_existing_config(tmp_path):
    """The langs are added to an existing .nudebomb.yaml, keeping its keys."""
    media = tmp_path / "media"
    anime = media / "anime"
    anime.mkdir(parents=True)
    (anime / ".lang").write_text("jpn\n")
    (anime / ".nudebomb.yaml").write_text(
        "nudebomb:\n  # keep me\n  title: false\n  languages: [deu]\n"
    )
    # Global languages come from the user config, not the CLI (which would
    # override the directory config's [deu] and shadow it).
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "config.yaml").write_text("nudebomb:\n  languages: [eng]\n")
    args = get_arguments(("nudebomb", str(media)))
    nudebomb_config = NudebombConfig()
    config = nudebomb_config.get_config(args)
    migrator = LangfileMigrator(
        config, LangFiles(config), DirConfig(nudebomb_config, args, config)
    )

    migrator.migrate_dir(media, anime)

    assert not (anime / ".lang").exists()
    text = (anime / ".nudebomb.yaml").read_text()
    assert "# keep me" in text  # comments preserved
    section = yaml_load(anime / ".nudebomb.yaml")["nudebomb"]
    assert section["title"] is False  # other keys preserved
    # deu (existing dir config) unioned with the langfile's jpn.
    assert set(section["languages"]) == {"deu", "jpn", "und"}


def test_migrate_unions_all_variants_and_deletes_them(tmp_path):
    """Every langfile variant in a dir is unioned and all are deleted."""
    media = tmp_path / "media"
    show = media / "show"
    show.mkdir(parents=True)
    (show / "lang").write_text("fra\n")
    (show / ".langs").write_text("spa\n")

    _migrator(media, "-l", "deu").migrate_dir(media, show)

    assert not (show / "lang").exists()
    assert not (show / ".langs").exists()
    assert _langs(show) == {"deu", "fra", "spa", "und"}


def test_migrate_nested_preserves_each_effective_set(tmp_path):
    """Post-order migration bakes each dir's full inherited keep-set."""
    media = tmp_path / "media"
    show = media / "anime" / "show"
    show.mkdir(parents=True)
    (media / "anime" / ".lang").write_text("jpn\n")
    (show / ".lang").write_text("kor\n")

    migrator = _migrator(media)
    migrator.migrate_dir(media, show)  # children first
    migrator.migrate_dir(media, media / "anime")

    assert _langs(show) == {"eng", "jpn", "kor", "und"}
    assert _langs(media / "anime") == {"eng", "jpn", "und"}


def test_migrate_empty_langfile_deleted_without_config(tmp_path):
    """An empty langfile is removed but writes no config (inheritance covers it)."""
    media = tmp_path / "media"
    directory = media / "d"
    directory.mkdir(parents=True)
    (directory / ".lang").write_text("\n  \n")

    _migrator(media).migrate_dir(media, directory)

    assert not (directory / ".lang").exists()
    assert not (directory / ".nudebomb.yaml").exists()


def test_migrate_no_langfile_is_noop(tmp_path):
    """A directory with no langfile is left untouched."""
    media = tmp_path / "media"
    directory = media / "d"
    directory.mkdir(parents=True)

    _migrator(media).migrate_dir(media, directory)

    assert not (directory / ".nudebomb.yaml").exists()


def test_migrate_records_stat(tmp_path):
    """Each migrated langfile is counted in stats."""
    media = tmp_path / "media"
    anime = media / "anime"
    anime.mkdir(parents=True)
    (anime / ".lang").write_text("jpn\n")
    stats = Stats()

    _migrator(media, stats=stats).migrate_dir(media, anime)

    assert stats.migrated_langfiles == 1


def _run_walk(tmp_path, *extra_argv: str) -> Path:
    """Run a full walk over a media tree containing an anime/.lang langfile."""
    media = tmp_path / "media"
    anime = media / "anime"
    anime.mkdir(parents=True)
    (anime / ".lang").write_text("jpn\n")
    argv = ("nudebomb", "-r", *extra_argv, "-l", "eng", str(media))
    args = get_arguments(argv)
    config = NudebombConfig().get_config(args)
    Walk(config, args).run()
    return anime


def test_walk_migrates_langfiles(tmp_path):
    """A normal run migrates langfiles found during the walk."""
    anime = _run_walk(tmp_path)
    assert not (anime / ".lang").exists()
    assert _langs(anime) == {"eng", "jpn", "und"}


def test_walk_dry_run_does_not_migrate(tmp_path):
    """A dry run never rewrites or deletes langfiles."""
    anime = _run_walk(tmp_path, "-d")
    assert (anime / ".lang").exists()
    assert not (anime / ".nudebomb.yaml").exists()
