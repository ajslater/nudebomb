"""Walk directory trees and strip mkvs."""
import os

from copy import deepcopy
from pathlib import Path

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
        self._langfiles = LangFiles(config.languages)
        self._timestamps: dict[Path, Treestamps] = {}

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
            return

        config = deepcopy(self._config)
        config.languages = self._langfiles.get_langs(top_path, path)
        mkv_obj = MKVFile(config, path)
        mkv_obj.remove_tracks()

        if self._config.timestamps:
            self._timestamps[top_path].set(path)

    def walk_dir(self, top_path, dir):
        """Walk a directory."""
        if not self._config.recurse:
            return

        dirs = []
        filenames = []

        for filename in os.scandir(dir):
            path = Path(filename)
            if path.is_dir():
                dirs.append(path)
            else:
                filenames.append(path)

        for path in sorted(dirs):
            self.walk_dir(top_path, path)

        for path in sorted(filenames):
            self.walk_file(top_path, path)

        if self._config.timestamps:
            timestamps = self._timestamps[top_path]
            timestamps.set(dir, compact=True)
            timestamps.dump()

    def walk_file(self, top_path, path):
        """Walk a file."""
        if path.is_symlink() and not self._config.symlinks:
            return
        if path.is_dir():
            self.walk_dir(top_path, path)
        else:
            self.strip_path(top_path, path)

    def run(self):
        """Run the stripper against all configured paths."""
        if self._config.verbose:
            print("Searching for MKV files to process...")

        if self._config.timestamps:
            self._timestamps = Treestamps.path_to_treestamps_map_factory(
                self._config.paths,
                PROGRAM_NAME,
                self._config.verbose,
                self._config,
                TIMESTAMPS_CONFIG_KEYS,
            )
        for path_str in self._config.paths:
            path = Path(path_str)
            top_path = Treestamps.dirpath(path)
            self.walk_file(top_path, path)

        if self._config.timestamps:
            for timestamps in self._timestamps.values():
                timestamps.dump()
