"""MKV file operations."""

from __future__ import annotations

import json
import subprocess
from collections import defaultdict
from pathlib import Path
from typing import TYPE_CHECKING, Final

from loguru import logger
from rich.rule import Rule
from rich.text import Text

from nudebomb.lang import lang_to_alpha3
from nudebomb.log import console
from nudebomb.log.reporter import Reporter
from nudebomb.track import Track

if TYPE_CHECKING:
    from collections.abc import Callable

    from rich.console import RenderableType

    from nudebomb.config import NudebombSettings


class MKVFile:
    """Strips matroska files of unwanted audio and subtitles."""

    VIDEO_TRACK_NAME: Final = "video"
    AUDIO_TRACK_NAME: Final = "audio"
    SUBTITLE_TRACK_NAME: Final = "subtitles"
    REMOVABLE_TRACK_NAMES: Final = (AUDIO_TRACK_NAME, SUBTITLE_TRACK_NAME)

    def __init__(
        self,
        config: NudebombSettings,
        path: Path,
        reporter: Reporter | None = None,
    ) -> None:
        """Initialize."""
        self._config: NudebombSettings = config
        self.path: Path = Path(path)
        self._reporter: Reporter = reporter if reporter is not None else Reporter()
        self._init_track_map()

    def update_languages(self, languages: frozenset[str]) -> None:
        """
        Inject a language set after init.

        Enables ``MKVFile.__init__`` (which runs ``mkvmerge -J``) to be
        kicked off before a DB lookup completes; the resolved language is
        folded in here just before ``remove_tracks`` does any filtering.
        """
        self._config.languages = languages

    def _init_track_map(self) -> None:
        self._track_map: dict[str, list[Track]] = {}

        # Ask mkvmerge for the json info. Identification problems exit
        # nonzero but still emit the JSON payload (with its "errors"
        # array), so parse stdout regardless of the exit code and record
        # problems per file instead of aborting the whole walk.
        command = (self._config.mkvmerge_bin, "-J", str(self.path))
        try:
            proc = subprocess.run(  # noqa: S603
                command,
                capture_output=True,
                check=False,
                text=True,
            )
            json_data = json.loads(proc.stdout)
        except (OSError, json.JSONDecodeError) as exc:
            msg = f"mkvmerge identification failed for {self.path}: {exc}"
            logger.error(msg)
            self._reporter.stats.record_error(self.path, msg)
            return

        # Process the json response
        if errors := json_data.get("errors"):
            for error in errors:
                logger.error(error)
                self._reporter.stats.record_error(self.path, error)
        if warnings := json_data.get("warnings"):
            for warning in warnings:
                logger.warning(warning)
                self._reporter.stats.record_warning(self.path, warning)
                self._reporter.progress.mark_warning()
        tracks = json_data.get("tracks")
        if not tracks:
            msg = f"No tracks. Might not be a valid matroshka video file: {self.path}"
            logger.warning(msg)
            self._reporter.stats.record_warning(self.path, msg)
            self._reporter.progress.mark_warning()
            return

        # load into our map.
        track_map: dict[str, list[Track]] = defaultdict(list)
        for track_data in tracks:
            track_obj = Track(track_data)
            track_map[track_obj.type].append(track_obj)
        self._track_map = track_map

    def _filtered_tracks(self, track_type: str) -> tuple[list[Track], list[Track]]:
        """Return a tuple consisting of tracks to keep and tracks to remove."""
        if track_type == self.SUBTITLE_TRACK_NAME and self._config.sub_languages:
            languages_to_keep = self._config.sub_languages
        else:
            languages_to_keep = self._config.languages

        # Lists of track to keep & remove
        remove = []
        keep = []
        # Iterate through all tracks to find which track to keep or remove
        tracks = self._track_map.get(track_type, [])
        for track in tracks:
            logger.info(f"\t{track_type}: {track.id} {track.lang}")
            track_lang = lang_to_alpha3(track.lang)
            if track_lang in languages_to_keep:
                # Tracks we want to keep
                keep.append(track)
            else:
                # Tracks we want to remove
                remove.append(track)

        if not keep and (track_type == self.AUDIO_TRACK_NAME or self._config.subtitles):
            # Never remove all audio
            # Do not remove all subtitles without option set.
            keep = remove
            remove = []

        return keep, remove

    def _extend_track_command(
        self,
        track_type: str,
        command: list[str],
        num_remove_ids: int,
    ) -> tuple[list[RenderableType], int]:
        """
        Extend ``command`` in place with keep/remove flags for ``track_type``.

        Returns ``(section, num_remove_ids)`` — a list of rich renderables
        describing what will happen to this track type, plus the running
        count of removed tracks.
        """
        keep, remove = self._filtered_tracks(track_type)
        section: list[RenderableType] = []

        # Build the keep tracks options
        keep_ids = set()

        retaining_lines: list[str] = []
        for count, track in enumerate(keep):
            keep_ids.add(track.id)
            retaining_lines.append(f"   {track}")

            # Set the first track as default
            command += [
                "--default-track",
                ":".join((track.id, "0" if count else "1")),
            ]
        if retaining_lines:
            section.append(Text(f"Retaining {track_type} track(s):", style="bold"))
            section.extend(Text(line) for line in retaining_lines)

        # Set which tracks are to be kept
        if keep_ids:
            prefix = track_type
            if track_type == self.SUBTITLE_TRACK_NAME:
                prefix = prefix[:-1]
            command += [f"--{prefix}-tracks", ",".join(sorted(keep_ids))]
        elif track_type == self.SUBTITLE_TRACK_NAME:
            command += ["--no-subtitles"]
        else:
            msg = f"No tracks to remove from {self.path}"
            logger.warning(msg)
            self._reporter.stats.record_warning(self.path, msg)
            self._reporter.progress.mark_warning()
            return section, num_remove_ids

        # Report what tracks will be removed
        if remove:
            section.append(Text(f"Removing {track_type} track(s):", style="bold"))
            section.extend(Text(f"   {track}") for track in remove)

        section.append(Rule(style="bright_black"))
        num_remove_ids += len(remove)

        return section, num_remove_ids

    @staticmethod
    def _remux_file_stdout_line(
        line: str,
        update_pct: Callable[[int], None],
        *,
        show_output: bool,
    ) -> None:
        """Route one mkvmerge output line to either the sub-task or the console."""
        if line.startswith("#GUI#progress"):
            try:
                pct = int(line.split()[-1].rstrip("%"))
            except (IndexError, ValueError):
                return
            update_pct(pct)
        elif line.startswith("#GUI#"):
            # Other GUI markers (begin/end_scanning_playlists, etc.)
            # carry no human-readable info — skip.
            return
        elif line and show_output:
            # markup=False: mkvmerge echoes file paths whose bracket tags
            # would parse as Rich markup (or raise MarkupError and falsely
            # fail the remux).
            console.print(line, markup=False, highlight=False)

    def _remux_file(self, command: list[str]) -> None:
        """
        Remux an mkv file with the given parameters.

        Drive a transient per-file sub-task on the shared Rich Progress
        from mkvmerge's ``--gui-mode`` progress lines (``#GUI#progress NN%``)
        so the percentage renders beneath the main bar inside the same
        Live region. Other (human-readable) lines from mkvmerge are
        printed through the shared Console so they scroll above the bar
        like log output — Rich keeps the bar pinned beneath them via
        the active Live region.

        ``stderr`` is merged into ``stdout`` (``stderr=subprocess.STDOUT``)
        so mkvmerge's own progress / warning output streams in real time
        through the same single-reader loop. Without the merge the user
        only ever saw stderr at end-of-process via the
        ``CalledProcessError`` payload on failure.
        """
        gui_command = [command[0], "--gui-mode", *command[1:]]
        show_output = self._config.verbose > 0
        collected: list[str] = []
        with (
            self._reporter.progress.file_subtask(f"  {self.path.name}") as update_pct,
            subprocess.Popen(  # noqa: S603
                gui_command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                bufsize=1,
                text=True,
            ) as process,
        ):
            if process.stdout is not None:
                for raw_line in process.stdout:
                    line = raw_line.rstrip()
                    collected.append(line)
                    self._remux_file_stdout_line(
                        line, update_pct, show_output=show_output
                    )

            if retcode := process.wait():
                raise subprocess.CalledProcessError(
                    retcode, gui_command, output="\n".join(collected)
                )

    def _extend_und_language_command(
        self,
        command: list[str],
    ) -> tuple[list[RenderableType], bool]:
        """
        Add ``--language`` flags in place to relabel ``und`` tracks.

        Returns ``(section, relabeled)`` — a list of rich renderables
        describing what will happen, plus a flag indicating whether any
        track was relabeled. All und tracks are kept tracks by
        construction: the config layer adds "und" to both language lists
        whenever und_language is set, and video is never filtered.
        """
        und_language = self._config.und_language
        if not und_language:
            return [], False

        section: list[RenderableType] = []
        relabel_lines: list[str] = []
        for tracks in self._track_map.values():
            for track in tracks:
                if track.lang == "und":
                    command += ["--language", f"{track.id}:{und_language}"]
                    relabel_lines.append(f"   {track} -> {und_language}")
        if relabel_lines:
            section.append(
                Text(f"Relabeling 'und' track(s) to '{und_language}':", style="bold")
            )
            section.extend(Text(line) for line in relabel_lines)
            section.append(Rule(style="bright_black"))

        return section, bool(relabel_lines)

    def _print_manifest(self, manifest: list[RenderableType]) -> None:
        """
        Print the planned-work manifest above the live progress bar.

        Gated on ``verbose > 0``: in quiet mode (``-q``) the per-file
        plan is suppressed along with everything else, but at default
        verbosity (1) it surfaces alongside mkvmerge's own output —
        ``logger.info`` would have buried it under the WARNING-level
        filter, which is the bug this method fixes.
        """
        if self._config.verbose <= 0:
            return
        console.rule(Text(f"Remuxing {self.path}", style="bold"), align="left")
        for renderable in manifest:
            console.print(renderable, highlight=False)

    def _build_remux_plan(
        self, tmp_path: Path
    ) -> tuple[list[RenderableType], list[str], bool]:
        """
        Build the mkvmerge command and a manifest describing the work.

        Returns ``(manifest, command, needs_work)``; ``needs_work`` is
        False when no track would be removed or relabeled.
        """
        command = [
            self._config.mkvmerge_bin,
            "--output",
            str(tmp_path),
        ]
        if self._config.title:
            command += [
                "--title",
                self.path.stem,
            ]

        # Iterate all tracks and mark which tracks are to be kept,
        # accumulating a list of rich renderables describing the plan.
        manifest: list[RenderableType] = []
        num_remove_ids = 0
        for track_type in self.REMOVABLE_TRACK_NAMES:
            section, num_remove_ids = self._extend_track_command(
                track_type, command, num_remove_ids
            )
            manifest.extend(section)

        # Relabel und tracks if configured
        und_section, und_relabeled = self._extend_und_language_command(command)
        manifest.extend(und_section)

        command.append(str(self.path))
        return manifest, command, bool(num_remove_ids or und_relabeled)

    def _execute_remux_plan(
        self,
        manifest: list[RenderableType],
        command: list[str],
        tmp_path: Path,
    ) -> bool:
        """Run (or dry-run) the built plan. Returns True if remuxed."""
        changed = False
        try:
            self._print_manifest(manifest)
            if self._config.dry_run:
                if self._config.verbose > 0:
                    console.print(
                        Text(
                            f"\tNot remuxing on dry run {self.path}",
                            style="bold bright_black",
                        ),
                        highlight=False,
                    )
                self._reporter.stats.record_dry_run(self.path)
                self._reporter.progress.mark_dry_run()
            else:
                self._remux_file(command)
                tmp_path.replace(self.path)
                changed = True
                self._reporter.stats.record_stripped(self.path)
                self._reporter.progress.mark_stripped()
        except (OSError, subprocess.SubprocessError) as exc:
            # Covers mkvmerge failures (CalledProcessError), a missing
            # binary, and filesystem errors from the tmp replace.
            logger.error(str(exc))
            self._reporter.stats.record_error(self.path, str(exc))
            self._reporter.progress.mark_error()
            tmp_path.unlink(missing_ok=True)
        return changed

    def remove_tracks(self) -> bool:
        """
        Remove the unwanted tracks.

        Returns True if the file is in the desired state — remuxed this
        run OR already-stripped before. Walk uses this to decide whether
        to write a timestamp; both states mean "no need to re-check this
        file next run". Dry-run and errors return False so the timestamp
        isn't poisoned.
        """
        if not self._track_map:
            msg = f"not removing tracks from mkv with no tracks: {self.path}"
            logger.error(msg)
            self._reporter.stats.record_error(self.path, msg)
            self._reporter.progress.mark_error()
            return False
        logger.debug(f"Checking {self.path}:")

        # Output the remuxed file to a temp file. This protects the
        # original from corruption if anything goes wrong.
        tmp_path = self.path.with_suffix(self.path.suffix + ".tmp")
        # A hard kill mid-remux can orphan the temp file; remove any
        # leftover so it can't outlive an already-stripped early return.
        tmp_path.unlink(missing_ok=True)

        manifest, command, needs_work = self._build_remux_plan(tmp_path)

        if not needs_work:
            logger.info(f"\tAlready stripped {self.path}")
            self._reporter.stats.record_already_stripped()
            self._reporter.progress.mark_already_stripped()
            # Already in the desired state — let Walk write the timestamp
            # so subsequent runs short-circuit on the timestamp check.
            return True

        return self._execute_remux_plan(manifest, command, tmp_path)
