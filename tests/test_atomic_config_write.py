"""Config writes are all-or-nothing, including the unattended migration."""

import os
from pathlib import Path

import pytest

from nudebomb.cli import get_arguments
from nudebomb.config import DirConfig, LangfileMigrator, LangFiles, NudebombConfig
from nudebomb.config.config import merge_config_file

__all__ = ()

OWNER_ONLY = 0o600
SEED = "# keep this comment\nnudebomb:\n  title: false\n"


@pytest.fixture(autouse=True)
def isolate_config(monkeypatch, tmp_path):
    """Point confuse at an empty config dir and scrub nudebomb env vars."""
    for key in list(os.environ):
        if key.startswith("NUDEBOMB"):
            monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("NUDEBOMBDIR", str(tmp_path / "config"))


def _migrator(media: Path) -> LangfileMigrator:
    """Build a LangfileMigrator for a media tree."""
    args = get_arguments(("nudebomb", "-l", "eng", str(media)))
    nudebomb_config = NudebombConfig()
    config = nudebomb_config.get_config(args)
    return LangfileMigrator(
        config, LangFiles(config), DirConfig(nudebomb_config, args, config)
    )


def _crash(*_args, **_kwargs) -> None:
    """Fail the way a full disk or a kill would."""
    msg = "simulated crash"
    raise OSError(msg)


class TestAtomicConfigWrite:
    """merge_config_file never leaves a truncated config behind."""

    def test_crash_during_replace_preserves_original(self, monkeypatch, tmp_path):
        """A crash at the rename leaves the target fully intact."""
        target = tmp_path / ".nudebomb.yaml"
        target.write_text(SEED)
        monkeypatch.setattr(Path, "replace", _crash)

        with pytest.raises(OSError, match="simulated crash"):
            merge_config_file(target, target, {"recurse": True})

        # Fully old: the comment survives and nothing new leaked in.
        assert target.read_text() == SEED
        # No temp droppings left behind.
        assert sorted(p.name for p in tmp_path.iterdir()) == [".nudebomb.yaml"]

    def test_successful_write_leaves_no_temp_files(self, tmp_path):
        """A normal write replaces the target and cleans up after itself."""
        target = tmp_path / ".nudebomb.yaml"
        target.write_text(SEED)

        merge_config_file(target, target, {"recurse": True})

        text = target.read_text()
        assert "# keep this comment" in text
        assert "recurse: true" in text
        assert "title: false" in text
        assert sorted(p.name for p in tmp_path.iterdir()) == [".nudebomb.yaml"]

    def test_written_config_is_owner_only(self, tmp_path):
        """The config can hold API keys, so it is never world readable."""
        target = tmp_path / ".nudebomb.yaml"
        merge_config_file(target, target, {"recurse": True})
        assert target.stat().st_mode & 0o777 == OWNER_ONLY

    def test_migration_failure_preserves_config_and_langfile(
        self, monkeypatch, tmp_path
    ):
        """
        A failed migration must destroy neither the config nor the langfile.

        The migrator runs unattended on every non-dry run and deletes the
        langfile right after writing, so a truncated write would lose the
        languages entirely.
        """
        media = tmp_path / "media"
        media.mkdir(parents=True)
        langfile = media / "langs"
        langfile.write_text("fra\n")
        config = media / ".nudebomb.yaml"
        config.write_text(SEED)

        migrator = _migrator(media)
        monkeypatch.setattr(Path, "replace", _crash)
        migrator.migrate_dir(media, media)

        # The write failed, so the langfile is kept for the next run.
        assert config.read_text() == SEED
        assert langfile.exists()
        assert sorted(p.name for p in media.iterdir()) == [".nudebomb.yaml", "langs"]
