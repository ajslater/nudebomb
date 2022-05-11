"""Walk directory trees and strip mkvs."""
import os

from copy import deepcopy
from pathlib import Path

from termcolor import cprint
from treestamps import Treestamps

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
        self._timestamps: dict[Path, Treestamps] = {}

    def _is_path_ignored(self, path: Path) -> bool:
        """Return if path should be ignored."""
        for ignore_glob in self._config.ignore:
            if path.match(ignore_glob):
                return True
        return False

    def strip_path(self, top_path, path):
        """Strip a single mkv file."""
        if not path.suffix == ".mkv":
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

        dirpath = Treestamps.dirpath(path)
        config = deepcopy(self._config)
        config.languages = self._langfiles.get_langs(top_path, dirpath)
        mkv_obj = MKVFile(config, path)
        mkv_obj.remove_tracks()

        if self._config.timestamps:
            self._timestamps[top_path].set(path)

    def walk_dir(self, top_path, dir):
        """Walk a directory."""
        if not self._config.recurse:
            return

        filenames = []

        for filename in sorted(os.listdir(dir)):
            entry_path = dir / filename
            if entry_path.is_dir():
                self.walk_file(top_path, entry_path)
            else:
                filenames.append(entry_path)

        for path in filenames:
            self.walk_file(top_path, path)

        if self._config.timestamps:
            timestamps = self._timestamps[top_path]
            timestamps.set(dir, compact=True)

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
        if self._config.sub_languages:
            audio = "audio "
        else:
            audio = ""
        print(f"Stripping {audio}languages except {langs}.")
        if self._config.sub_languages:
            sub_langs = ", ".join(sorted(self._config.sub_languages))
            print(f"Stripping subtitle languages except {sub_langs}.")

        print("Searching for MKV files to process", end="")
        if self._config.verbose:
            print(":")

    def run(self):
        """Run the stripper against all configured paths."""
        self.print_info()

        if self._config.timestamps:
            self._timestamps = Treestamps.map_factory(
                self._config.paths,
                PROGRAM_NAME,
                self._config.verbose,
                self._config.symlinks,
                self._config.ignore,
                self._config,
                TIMESTAMPS_CONFIG_KEYS,
            )
        for path_str in self._config.paths:
            path = Path(path_str)
            top_path = Treestamps.dirpath(path)
            self.walk_file(top_path, path)
        if not self._config.verbose:
            print("done.")

        if self._config.timestamps:
            for top_path, timestamps in self._timestamps.items():
                print(f"Saving timestamps for {top_path}")
                timestamps.dump()
