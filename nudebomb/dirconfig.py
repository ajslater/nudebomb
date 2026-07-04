"""Discover and resolve per-directory ``.nudebomb.yaml`` config files."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from confuse.exceptions import ConfigError
from loguru import logger
from ruamel.yaml.error import YAMLError

from nudebomb.config import DIR_CONFIG_FILENAME

if TYPE_CHECKING:
    from argparse import Namespace

    from nudebomb.config import NudebombConfig, NudebombSettings
    from nudebomb.log.summary import Stats


class DirConfig:
    """
    Resolve the effective settings for a directory from ``.nudebomb.yaml`` files.

    Mirrors :class:`nudebomb.langfiles.LangFiles`: it walks up the tree from
    a file's directory to the CLI target root (``top_path``), collecting the
    ``.nudebomb.yaml`` files along the way, and layers them beneath env vars
    and CLI args (via :meth:`NudebombConfig.get_dir_settings`). Results are
    cached per directory so cost is O(unique dirs), not O(files), and a fast
    path returns the run-wide settings untouched when no directory config
    applies.
    """

    def __init__(
        self,
        nudebomb_config: NudebombConfig,
        args: Namespace | None,
        global_settings: NudebombSettings,
        stats: Stats | None = None,
    ) -> None:
        """Initialize caches and the resolver dependencies."""
        self._nudebomb_config: NudebombConfig = nudebomb_config
        self._args: Namespace | None = args
        self._global_settings: NudebombSettings = global_settings
        self._stats: Stats | None = stats
        # Cache of each directory's readable config file (or None).
        self._dir_config_files: dict[Path, Path | None] = {}
        # Cache of resolved settings keyed by the file's directory.
        self._settings: dict[Path, NudebombSettings] = {}
        # Failure reasons already reported, so each is logged only once.
        self._failed: set[str] = set()

    def _dir_config_file(self, path: Path) -> Path | None:
        """Return ``path``'s readable ``.nudebomb.yaml``, or None. Cached."""
        if path not in self._dir_config_files:
            config_file = path / DIR_CONFIG_FILENAME
            # Use the run-wide symlinks setting to decide whether to read a
            # config file: a file can't be trusted to say whether it should
            # itself be read.
            found = (
                config_file
                if config_file.is_file()
                and (self._global_settings.symlinks or not config_file.is_symlink())
                else None
            )
            self._dir_config_files[path] = found
        return self._dir_config_files[path]

    def _discover(self, top_path: Path, dir_path: Path) -> tuple[Path, ...]:
        """
        Collect ``.nudebomb.yaml`` files from ``top_path`` down to ``dir_path``.

        Walks UP from ``dir_path`` to ``top_path`` (the ``LangFiles`` boundary
        idiom, bounded at the CLI target root so nothing above it is read),
        then reverses so the result is shallowest→deepest — the order
        ``confuse.set_file`` needs for deeper directories to win.
        """
        files: list[Path] = []
        path = dir_path
        # Check the boundary only after visiting the current dir so
        # top_path's own config applies to nested paths too.
        while True:
            if (config_file := self._dir_config_file(path)) is not None:
                files.append(config_file)
            if path in (top_path, path.parent):
                break
            path = path.parent
        files.reverse()
        return tuple(files)

    def _record_failure(self, dir_files: tuple[Path, ...], exc: Exception) -> None:
        """Log a directory-config failure once per offending file."""
        # confuse names the offending file in its message, and it is stable
        # across descendant directories that re-read the same bad ancestor,
        # so deduping on the reason logs each broken file exactly once.
        reason = str(exc)
        if reason in self._failed:
            return
        self._failed.add(reason)
        # OSError carries the path; confuse/YAML errors put it in the reason.
        config_file = Path(getattr(exc, "filename", None) or dir_files[-1])
        msg = f"Could not read directory config: {reason}"
        logger.error(msg)
        if self._stats is not None:
            self._stats.record_error(config_file, msg)

    def get_settings(self, top_path: Path, dir_path: Path) -> NudebombSettings:
        """
        Resolve the effective settings for ``dir_path``.

        Returns the run-wide settings unchanged when no ``.nudebomb.yaml``
        applies (fast path). Otherwise rebuilds a confuse Configuration with
        the discovered directory files layered beneath env/CLI and caches the
        result per directory. A malformed or unreadable directory file is
        isolated: logged once, recorded in stats, and the directory falls back
        to the run-wide settings so the walk continues.
        """
        if (cached := self._settings.get(dir_path)) is not None:
            return cached
        dir_files = self._discover(top_path, dir_path)
        if not dir_files:
            return self._global_settings
        try:
            settings = self._nudebomb_config.get_dir_settings(self._args, dir_files)
        except (ConfigError, YAMLError, OSError) as exc:
            self._record_failure(dir_files, exc)
            settings = self._global_settings
        self._settings[dir_path] = settings
        return settings
