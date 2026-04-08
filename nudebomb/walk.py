"""Walk directory trees and strip mkvs."""

from copy import deepcopy
from pathlib import Path

from confuse import AttrDict
from treestamps import Grovestamps, GrovestampsConfig
from treestamps.tree import Treestamps

from nudebomb.config import TIMESTAMPS_CONFIG_KEYS
from nudebomb.langfiles import LangFiles
from nudebomb.mkv import MKVFile
from nudebomb.printer import Printer
from nudebomb.tmdb import TMDBLookup
from nudebomb.version import PROGRAM_NAME


class Walk:
    """Directory traversal class."""

    def __init__(self, config: AttrDict) -> None:
        """Initialize."""
        self._config: AttrDict = config
        self._langfiles: LangFiles = LangFiles(config)
        self._printer: Printer = Printer(self._config.verbose)
        self._timestamps: Grovestamps | None = None
        self._tmdb: TMDBLookup | None = None
        if config.tmdb_api_key:
            self._tmdb = TMDBLookup(config)

    def _is_path_suffix_not_mkv(self, path: Path) -> bool:
        """Return if the suffix should skipped."""
        if path.suffix == ".mkv":
            return False
        self._printer.skip("Suffix is not 'mkv'", path)
        return True

    def _is_path_ignored(self, path: Path) -> bool:
        """Return if path should be ignored."""
        if any(path.match(ignore_glob) for ignore_glob in self._config.ignore):
            self._printer.skip("ignored", path)

            return True
        return False

    def _is_path_before_timestamp(self, top_path: Path, path: Path) -> bool:
        """Return if the file was last updated before the timestamp."""
        if self._config.after:
            mtime: float | None = self._config.after
        elif self._timestamps:
            mtime = self._timestamps.get(top_path, {}).get(path)
        else:
            mtime = None

        if mtime is not None and mtime > path.stat().st_mtime:
            self._printer.skip_timestamp(f"Skip by timestamps {path}")
            return True
        return False

    def _is_path_skippable_symlink(self, path: Path) -> bool:
        if not self._config.symlinks and path.is_symlink():
            self._printer.skip("symlink", path)
            return True
        return False

    def strip_path(
        self,
        top_path: Path,
        path: Path,
    ) -> None:
        """Strip a single mkv file."""
        dir_path = Treestamps.get_dir(path)
        config = deepcopy(self._config)
        config.languages = self._langfiles.get_langs(top_path, dir_path)

        # TMDB fallback when no lang files contributed languages
        if self._tmdb and not self._langfiles.found_lang_files(top_path, dir_path):
            tmdb_lang = self._tmdb.lookup_language(path)
            if tmdb_lang:
                config.languages = frozenset(config.languages | {tmdb_lang})

        mkv_obj = MKVFile(config, path)
        mkv_obj.remove_tracks()
        if self._timestamps:
            self._timestamps[top_path].set(path)

    def walk_dir(
        self,
        top_path: Path,
        dir_path: Path,
    ) -> bool:
        """Walk a directory."""
        if not self._config.recurse:
            return False

        filenames = []

        wrote = False
        for filename in sorted(dir_path.iterdir()):
            if filename.is_dir():
                wrote |= self.walk_file(top_path, filename)
            else:
                filenames.append(filename)

        for path in filenames:
            wrote |= self.walk_file(top_path, path)

        if self._timestamps:
            timestamps = self._timestamps[top_path]
            timestamps.set(dir_path, compact=True)
        return wrote

    def walk_file(self, top_path: Path, path: Path) -> bool:
        """Walk a file."""
        if self._is_path_ignored(path):
            return False
        if self._is_path_skippable_symlink(path):
            return False
        if path.is_dir():
            return self.walk_dir(top_path, path)
        if self._is_path_suffix_not_mkv(path):
            return False
        if self._is_path_before_timestamp(top_path, path):
            return False
        self.strip_path(top_path, path)
        return True

    def run(self) -> None:
        """Run the stripper against all configured paths."""
        self._printer.print_config(self._config.languages, self._config.sub_languages)
        self._printer.start_operation()

        if self._config.timestamps:
            grove_config = GrovestampsConfig(
                PROGRAM_NAME,
                paths=self._config.paths,
                verbose=self._config.verbose,
                symlinks=self._config.symlinks,
                ignore=self._config.ignore,
                check_config=self._config.timestamps_check_config,
                program_config=self._config,
                program_config_keys=TIMESTAMPS_CONFIG_KEYS,
            )
            self._timestamps = Grovestamps(grove_config)

        noop_top_paths: set[Path] = set()
        for path_str in self._config.paths:
            path = Path(path_str)
            top_path = Treestamps.get_dir(path)
            if not self.walk_file(top_path, path):
                noop_top_paths.add(top_path)
        self._printer.done()

        if self._timestamps:
            self._timestamps.dumpf(noop_top_paths=noop_top_paths)
