"""Walk directory trees and strip mkvs."""

from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path
from typing import TYPE_CHECKING, Final

from loguru import logger
from treestamps import Grovestamps, GrovestampsConfig
from treestamps.tree import Treestamps

from nudebomb.config import TIMESTAMPS_CONFIG_KEYS
from nudebomb.langfiles import LangFiles
from nudebomb.log import console
from nudebomb.log.progress import make_progress
from nudebomb.log.reporter import Reporter
from nudebomb.log.summary import Stats
from nudebomb.log.summary import render as render_summary
from nudebomb.lookup import TMDBLookup, TVDBLookup
from nudebomb.lookup.parser import parse_title
from nudebomb.mkv import MKVFile
from nudebomb.version import PROGRAM_NAME

if TYPE_CHECKING:
    from confuse import AttrDict

# Canonical key shape: (namespace, key_a, key_b). Namespaces are cheap
# strings so the same dict handles both id-based and title-based lookups.
_LookupKey = tuple[str, str, str]

# Hard cap to protect TMDB/TVDB rate limits even if the user cranks the knob.
_MAX_LOOKUP_WORKERS: Final = 8


class Walk:
    """Directory traversal class."""

    def __init__(self, config: AttrDict) -> None:
        """Initialize."""
        self._config: AttrDict = config
        self._stats: Stats = Stats(
            timestamps_active=bool(config.timestamps or config.after),
            dry_run_active=bool(config.dry_run),
            remote_db_active=bool(config.tmdb_api_key or config.tvdb_api_key),
        )
        # Progress is built later (in run()) once we know the total count.
        self._reporter: Reporter = Reporter(stats=self._stats)
        self._langfiles: LangFiles = LangFiles(config, stats=self._stats)
        self._timestamps: Grovestamps | None = None
        self._tmdb: TMDBLookup | None = (
            TMDBLookup(config, self._reporter) if config.tmdb_api_key else None
        )
        self._tvdb: TVDBLookup | None = (
            TVDBLookup(config, self._reporter) if config.tvdb_api_key else None
        )
        self._executor: ThreadPoolExecutor | None = None
        # Walk-wide future map keyed by canonical cache key.
        # The first file in a (title, year) / (id_type, id_value) group
        # submits the lookup; later files reuse the same future.
        self._pending: dict[_LookupKey, Future[str | None]] = {}

    # ------------------------------------------------------------------
    # Guards
    # ------------------------------------------------------------------

    def _is_path_suffix_not_mkv(self, path: Path) -> bool:
        """Return if the suffix should skipped."""
        if path.suffix == ".mkv":
            return False
        logger.debug(f"Skip: Suffix is not 'mkv': {path}")
        self._stats.record_ignored()
        self._reporter.progress.mark_ignored()
        return True

    def _is_path_ignored(self, path: Path) -> bool:
        """Return if path should be ignored."""
        if any(path.match(ignore_glob) for ignore_glob in self._config.ignore):
            logger.debug(f"Skip: ignored: {path}")
            self._stats.record_ignored()
            self._reporter.progress.mark_ignored()
            return True
        return False

    def _is_path_before_timestamp(self, top_path: Path, path: Path) -> bool:
        """Return if the file was last updated before the timestamp."""
        if self._config.after:
            mtime: float | None = self._config.after
        elif self._timestamps:
            mtime = self._timestamps.get_timestamp(top_path, path)
        else:
            mtime = None

        if mtime is not None and mtime > path.stat().st_mtime:
            logger.debug(f"Skip by timestamps {path}")
            self._stats.record_skipped_timestamp()
            self._reporter.progress.mark_skipped_timestamp()
            return True
        return False

    def _is_path_skippable_symlink(self, path: Path) -> bool:
        if not self._config.symlinks and path.is_symlink():
            logger.debug(f"Skip: symlink: {path}")
            self._stats.record_ignored()
            self._reporter.progress.mark_ignored()
            return True
        return False

    def _would_strip(self, top_path: Path, path: Path) -> bool:
        """
        Silent version of ``walk_file``'s guards.

        Used to decide whether prefetching a lookup is worthwhile — does
        not emit skip messages; ``walk_file`` prints those on the main pass.
        """
        if path.is_dir() or path.suffix != ".mkv":
            return False
        if any(path.match(ignore_glob) for ignore_glob in self._config.ignore):
            return False
        if not self._config.symlinks and path.is_symlink():
            return False
        if self._config.after:
            mtime: float | None = self._config.after
        elif self._timestamps:
            mtime = self._timestamps.get_timestamp(top_path, path)
        else:
            mtime = None
        return not (mtime is not None and mtime > path.stat().st_mtime)

    # ------------------------------------------------------------------
    # Pre-walk file count (drives a determinate progress bar)
    # ------------------------------------------------------------------

    def _count_dir(self, top_path: Path, dir_path: Path) -> int:
        """Recurse a directory mirroring walk_file/walk_dir's guards."""
        if not self._config.recurse:
            return 0
        total = 0
        try:
            entries = sorted(dir_path.iterdir())
        except OSError:
            return 0
        for entry in entries:
            total += self._count_path(top_path, entry)
        return total

    def _count_path(self, top_path: Path, path: Path) -> int:
        """Count files under a single path, mirroring walk_file's guards."""
        if any(path.match(ignore_glob) for ignore_glob in self._config.ignore):
            return 1  # still represents one bar advance via mark_ignored
        if not self._config.symlinks and path.is_symlink():
            return 1
        if path.is_dir():
            return self._count_dir(top_path, path)
        # Every visited non-dir entry contributes exactly one bar advance:
        # either the file is processed (stripped/dry-run/already-stripped/
        # error) or it gets skipped (non-mkv suffix, timestamp).
        return 1

    def _count_total(self) -> int:
        """Total advance count for the progress bar across all configured paths."""
        total = 0
        for path_str in self._config.paths:
            path = Path(path_str)
            top_path = Treestamps.get_dir(path)
            total += self._count_path(top_path, path)
        return total

    # ------------------------------------------------------------------
    # Lookup dispatch
    # ------------------------------------------------------------------

    def _has_lookup_backend(self) -> bool:
        return self._tmdb is not None or self._tvdb is not None

    def _lookup_key(self, path: Path) -> _LookupKey | None:
        """
        Canonical cache key for de-dup across files in a walk.

        Matches the cache keys used by :class:`LookupCache` so two files
        that would hit the same cache entry share a single future.
        """
        parsed = parse_title(path.stem, self._config.media_type)
        if parsed.tvdb_id:
            return ("tv", "tvdb", parsed.tvdb_id)
        if parsed.tmdb_id:
            return ("", "tmdb", parsed.tmdb_id)
        if parsed.imdb_id:
            return ("", "imdb", parsed.imdb_id)
        if parsed.title:
            return (self._config.media_type or "", parsed.title, parsed.year)
        return None

    def _do_lookup(self, path: Path) -> str | None:
        """
        Run the configured lookups in TVDB-first-then-TMDB order.

        Executed on a worker thread; the lookup classes log / advance
        progress / record stats inline (loguru and rich.Progress are both
        thread-safe, and Stats has its own lock).
        """
        lang: str | None = None
        if self._tvdb and self._config.media_type == "tv":
            lang = self._tvdb.lookup_language(path)
        if not lang and self._tmdb:
            lang = self._tmdb.lookup_language(path)
        return lang

    def _submit_lookup(self, path: Path) -> Future[str | None] | None:
        """Submit (or reuse) a lookup future for ``path``."""
        if self._executor is None or not self._has_lookup_backend():
            return None
        key = self._lookup_key(path)
        if key is None:
            return None
        if (future := self._pending.get(key)) is not None:
            return future
        future = self._executor.submit(self._do_lookup, path)
        self._pending[key] = future
        return future

    def _get_or_submit_lookup(
        self, top_path: Path, dir_path: Path, path: Path
    ) -> Future[str | None] | None:
        """
        Return the lookup future for ``path``, submitting if needed.

        Lang files on any ancestor short-circuit the online lookup, matching
        today's behavior in :meth:`strip_path`.
        """
        if not self._has_lookup_backend():
            return None
        if self._langfiles.found_lang_files(top_path, dir_path):
            return None
        return self._submit_lookup(path)

    # ------------------------------------------------------------------
    # Core per-file processing
    # ------------------------------------------------------------------

    def strip_path(
        self,
        top_path: Path,
        path: Path,
    ) -> bool:
        """Strip a single mkv file."""
        dir_path = Treestamps.get_dir(path)
        config = deepcopy(self._config)
        config.languages = self._langfiles.get_langs(top_path, dir_path)

        lookup_future = self._get_or_submit_lookup(top_path, dir_path, path)

        # Run mkvmerge -J now — it doesn't need lookup results, so it
        # overlaps with the in-flight DB call.
        mkv_obj = MKVFile(config, path, self._reporter)

        # Now fold the (usually-already-resolved) lookup into languages.
        if lookup_future is not None:
            lang = lookup_future.result()
            if lang:
                mkv_obj.update_languages(frozenset(config.languages | {lang}))

        return mkv_obj.remove_tracks()

    # ------------------------------------------------------------------
    # Directory walking
    # ------------------------------------------------------------------

    def _prefetch_dir_lookups(
        self, top_path: Path, dir_path: Path, mkv_files: list[Path]
    ) -> None:
        """
        Submit lookups for mkvs in ``dir_path`` before processing any.

        Keeps the executor saturated: lookups for files 2..N run while
        file 1's ``mkvmerge -J`` / remux is happening.
        """
        if not mkv_files or not self._has_lookup_backend():
            return
        # Prime lang-file reads for this directory so found_lang_files
        # reflects actual state (the first read populates _lang_roots).
        self._langfiles.get_langs(top_path, dir_path)
        if self._langfiles.found_lang_files(top_path, dir_path):
            return
        for path in mkv_files:
            if self._would_strip(top_path, path):
                self._submit_lookup(path)

    def walk_dir(
        self,
        top_path: Path,
        dir_path: Path,
    ) -> None:
        """Walk a directory."""
        if not self._config.recurse:
            return

        mkv_files: list[Path] = []
        other_files: list[Path] = []

        for filename in sorted(dir_path.iterdir()):
            if filename.is_dir():
                self.walk_file(top_path, filename)
            elif filename.suffix == ".mkv":
                mkv_files.append(filename)
            else:
                other_files.append(filename)

        self._prefetch_dir_lookups(top_path, dir_path, mkv_files)

        for path in mkv_files:
            self.walk_file(top_path, path)
        for path in other_files:
            self.walk_file(top_path, path)

        if self._timestamps:
            self._timestamps.set(top_path, dir_path, compact=True)

    def walk_file(self, top_path: Path, path: Path) -> None:
        """Walk a file."""
        if self._is_path_ignored(path):
            return
        if self._is_path_skippable_symlink(path):
            return
        if path.is_dir():
            self.walk_dir(top_path, path)
            return
        if self._is_path_suffix_not_mkv(path):
            return
        if self._is_path_before_timestamp(top_path, path):
            return
        # `up_to_date` is True for both freshly-remuxed files and files
        # that were already stripped — both states mean "no need to
        # re-check next run", so write the timestamp.
        up_to_date = self.strip_path(top_path, path)
        if self._timestamps and up_to_date:
            self._timestamps.set(top_path, path)

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------

    def _print_config(self) -> None:
        """Log the keep-languages config at INFO."""
        langs = ", ".join(sorted(self._config.languages))
        audio = "audio " if self._config.sub_languages else ""
        logger.info(f"Stripping {audio}languages except {langs}.")
        if self._config.sub_languages:
            sub_langs = ", ".join(sorted(self._config.sub_languages))
            logger.info(f"Stripping subtitle languages except {sub_langs}.")

    def run(self) -> None:
        """Run the stripper against all configured paths."""
        self._print_config()
        logger.info("Searching for MKV files to process…")

        if self._config.timestamps:
            # Force `verbose=0` so treestamps's own termcolor Printer
            # stays silent. At verbose>=1 it would emit `\x1b[2m\x1b[90m.`
            # dots straight to stdout for each `.set()` call, bypassing
            # rich's Live region and breaking the bar's in-place redraw.
            grove_config = GrovestampsConfig(
                PROGRAM_NAME,
                paths=self._config.paths,
                verbose=0,
                symlinks=self._config.symlinks,
                ignore=self._config.ignore,
                check_config=self._config.timestamps_check_config,
                program_config=self._config,
                program_config_keys=TIMESTAMPS_CONFIG_KEYS,
            )
            self._timestamps = Grovestamps(grove_config)

        total = self._count_total()
        progress = make_progress(total, console, enabled=self._config.verbose > 0)
        # Replace the no-op progress that lookup classes captured at
        # construction time so they advance the real bar.
        self._reporter.progress = progress

        max_workers = max(1, min(int(self._config.lookup_workers), _MAX_LOOKUP_WORKERS))
        with (
            progress,
            ThreadPoolExecutor(
                max_workers=max_workers,
                thread_name_prefix="nb-lookup",
            ) as executor,
        ):
            self._executor = executor
            try:
                for path_str in self._config.paths:
                    path = Path(path_str)
                    top_path = Treestamps.get_dir(path)
                    self.walk_file(top_path, path)
            finally:
                self._executor = None

        if self._timestamps:
            self._timestamps.dumpf()

        if self._config.verbose > 0:
            render_summary(self._stats, console)
