"""Migrate deprecated langfiles to per-directory ``.nudebomb.yaml`` files."""

from __future__ import annotations

from typing import TYPE_CHECKING

from loguru import logger
from ruamel.yaml.error import YAMLError

from nudebomb.config.config import DIR_CONFIG_FILENAME, merge_config_file
from nudebomb.config.langfiles import LANGS_FNS

if TYPE_CHECKING:
    from pathlib import Path

    from nudebomb.config.config import NudebombSettings
    from nudebomb.config.dirconfig import DirConfig
    from nudebomb.config.langfiles import LangFiles
    from nudebomb.log.summary import Stats


class LangfileMigrator:
    """
    Convert a directory's legacy langfiles into a ``.nudebomb.yaml``.

    Langfiles (``lang``/``langs``/``.lang``/``.langs``) are deprecated in
    favor of ``.nudebomb.yaml``. For a directory that has one, the migrator
    writes the directory's *effective* keep-set (the resolved config
    languages unioned with every langfile language up the tree) into
    ``languages`` — creating the ``.nudebomb.yaml`` or merging into an
    existing one, preserving its other keys and comments — then deletes the
    langfiles. Writing the full effective set keeps behavior unchanged under
    the replace semantics of directory configs.

    Meant to run per directory in post-order during the walk (children before
    parents), so a directory's langfiles are still on disk when a descendant
    resolves its inherited languages.
    """

    def __init__(
        self,
        config: NudebombSettings,
        langfiles: LangFiles,
        dirconfig: DirConfig,
        stats: Stats | None = None,
    ) -> None:
        """Initialize with the walk's shared LangFiles and DirConfig."""
        self._config: NudebombSettings = config
        self._langfiles: LangFiles = langfiles
        self._dirconfig: DirConfig = dirconfig
        self._stats: Stats | None = stats

    def _dir_langfiles(self, dir_path: Path) -> list[Path]:
        """Return the readable langfiles physically present in ``dir_path``."""
        found: list[Path] = []
        for fn in sorted(LANGS_FNS):
            path = dir_path / fn
            # Match LangFiles' read policy: skip symlinks when disallowed.
            if path.is_file() and (self._config.symlinks or not path.is_symlink()):
                found.append(path)
        return found

    def _write_migrated_config(self, top_path: Path, dir_path: Path) -> bool:
        """Write the preserved effective languages into ``dir_path``'s config."""
        effective = self._dirconfig.get_settings(
            top_path, dir_path
        ).languages | self._langfiles.get_extra_langs(top_path, dir_path)
        target = dir_path / DIR_CONFIG_FILENAME
        try:
            merge_config_file(target, target, {"languages": sorted(effective)})
        except (YAMLError, OSError) as exc:
            # Non-fatal: keep the langfiles so nothing is lost, and let the
            # rest of the run continue.
            msg = f"Could not migrate langfile in {dir_path}: {exc}"
            logger.error(msg)
            if self._stats is not None:
                self._stats.record_error(dir_path, msg)
            return False
        logger.info(f"Migrated langfile(s) in {dir_path} to {target.name}")
        return True

    def migrate_dir(self, top_path: Path, dir_path: Path) -> None:
        """Migrate ``dir_path``'s langfiles to ``.nudebomb.yaml`` and delete them."""
        langfiles = self._dir_langfiles(dir_path)
        if not langfiles:
            return
        # Only write a config when the langfiles actually contribute languages;
        # an empty langfile is just deleted (inheritance already preserves it).
        has_langs = bool(self._langfiles.read_lang_files(dir_path))
        if has_langs and not self._write_migrated_config(top_path, dir_path):
            return
        for langfile in langfiles:
            try:
                langfile.unlink()
            except OSError as exc:
                # A leftover langfile is harmless (its langs are already in the
                # new config) and will be retried next run.
                logger.warning(f"Could not delete langfile {langfile}: {exc}")
            else:
                if has_langs and self._stats is not None:
                    self._stats.record_langfile_migrated()
