"""Walk directory trees and strip mkvs."""

import os
from copy import deepcopy
from pathlib import Path

from termcolor import cprint
from treestamps import Grovestamps, GrovestampsConfig
from treestamps.tree import Treestamps

from nudebomb.config import TIMESTAMPS_CONFIG_KEYS
from nudebomb.langfiles import LangFiles
from nudebomb.mkv import MKVFile
from nudebomb.version import PROGRAM_NAME


class Walk:
    """Directory traversal class."""

    def __init__(self, config):
        """Initialize."""
        self._config = config
        self._langfiles = LangFiles(config)

    def _is_path_ignored(self, path: Path) -> bool:
        """Return if path should be ignored."""
        return any(path.match(ignore_glob) for ignore_glob in self._config.ignore)

    def strip_path(self, top_path, path):
        """Strip a single mkv file."""
        if path.suffix != ".mkv":
            return

        mtime = None
        if self._config.after:
            mtime = self._config.after
        elif self._config.timestamps:
            mtime = self._timestamps.get(top_path, {}).get(path)

        if mtime is not None and mtime > path.stat().st_mtime:
            if self._config.verbose:
                cprint(f"Skip unchanged {path}", "cyan", attrs=["dark"])
            else:
                cprint(".", "cyan", end="")
            return

        dir_path = Treestamps.get_dir(path)
        config = deepcopy(self._config)
        config.languages = self._langfiles.get_langs(top_path, dir_path)
        mkv_obj = MKVFile(config, path)
        mkv_obj.remove_tracks()

        if self._config.timestamps:
            self._timestamps[top_path.resolve()].set(path)

    def walk_dir(self, top_path, dir_path):
        """Walk a directory."""
        if not self._config.recurse:
            return

        filenames = []

        for filename in sorted(os.listdir(dir_path)):
            entry_path = dir_path / filename
            if entry_path.is_dir():
                self.walk_file(top_path, entry_path)
            else:
                filenames.append(entry_path)

        for path in filenames:
            self.walk_file(top_path, path)

        if self._config.timestamps:
            timestamps = self._timestamps[top_path.resolve()]
            timestamps.set(dir_path, compact=True)

    def walk_file(self, top_path, path):
        """Walk a file."""
        if self._is_path_ignored(path):
            if self._config.verbose:
                cprint(f"Skip ignored {path}", "white", attrs=["dark"])
            else:
                cprint(".", "white", attrs=["dark"], end="")
            return
        if not self._config.symlinks and path.is_symlink():
            if self._config.verbose:
                cprint(f"Skip symlink {path}", "white", attrs=["dark"])
            else:
                cprint(".", "white", attrs=["dark"], end="")
            return
        if path.is_dir():
            self.walk_dir(top_path, path)
        else:
            self.strip_path(top_path, path)

    def print_info(self):
        """Print intentions before we begin."""
        langs = ", ".join(sorted(self._config.languages))
        audio = "audio " if self._config.sub_languages else ""
        cprint(f"Stripping {audio}languages except {langs}.")
        if self._config.sub_languages:
            sub_langs = ", ".join(sorted(self._config.sub_languages))
            cprint(f"Stripping subtitle languages except {sub_langs}.")

        cprint("Searching for MKV files to process", end="")
        if self._config.verbose:
            cprint(":")

    def run(self):
        """Run the stripper against all configured paths."""
        self.print_info()

        if self._config.timestamps:
            paths = tuple(str(Path(path).resolve()) for path in self._config.paths)
            copse_config = GrovestampsConfig(
                PROGRAM_NAME,
                paths=paths,
                verbose=self._config.verbose,
                symlinks=self._config.symlinks,
                ignore=self._config.ignore,
                check_config=self._config.timestamps_check_config,
                program_config=self._config,
                program_config_keys=TIMESTAMPS_CONFIG_KEYS,
            )
            self._timestamps = Grovestamps(copse_config)

        for path_str in self._config.paths:
            path = Path(path_str)
            top_path = Treestamps.get_dir(path)
            self.walk_file(top_path, path)
        if not self._config.verbose:
            cprint("done.")

        if self._config.timestamps:
            self._timestamps.dump()
