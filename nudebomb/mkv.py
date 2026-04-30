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

        # Ask mkvmerge for the json info
        command = (self._config.mkvmerge_bin, "-J", str(self.path))
        proc = subprocess.run(  # noqa: S603
            command,
            capture_output=True,
            check=True,
            text=True,
        )

        # Process the json response
        json_data = json.loads(proc.stdout)
        if errors := json_data.get("errors"):
            for error in errors:
                logger.error(error)
                self._reporter.stats.record_error(self.path, error)
        if warnings := json_data.get("warnings"):
            for warning in warnings:
                logger.warning(warning)
                self._reporter.stats.record_warning(self.path, warning)
        tracks = json_data.get("tracks")
        if not tracks:
            msg = f"No tracks. Might not be a valid matroshka video file: {self.path}"
            logger.warning(msg)
            self._reporter.stats.record_warning(self.path, msg)
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
    ) -> tuple[list[RenderableType], list[str], int]:
        """
        Extend ``command`` with the keep/remove flags for ``track_type``.

        Returns ``(section, command, num_remove_ids)`` — a list of rich
        renderables describing what will happen to this track type, plus
        the augmented mkvmerge command and the running count of removed
        tracks.
        """
        keep, remove = self._filtered_tracks(track_type)
        section: list[RenderableType] = []

        # Build the keep tracks options
        keep_ids = set()

        retaining_lines: list[str] = []
        for count, track in enumerate(keep):
            keep_ids.add(str(track.id))
            retaining_lines.append(f"   {track}")

            # Set the first track as default
            command += [
                "--default-track",
                ":".join((str(track.id), "0" if count else "1")),
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
            return section, command, num_remove_ids

        # Report what tracks will be removed
        if remove:
            section.append(Text(f"Removing {track_type} track(s):", style="bold"))
            section.extend(Text(f"   {track}") for track in remove)

        section.append(Rule(style="bright_black"))
        num_remove_ids += len(remove)

        return section, command, num_remove_ids

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
            console.print(line, highlight=False)

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
    ) -> tuple[list[RenderableType], list[str], bool]:
        """
        Add ``--language`` flags to relabel ``und`` tracks.

        Returns ``(section, command, relabeled)`` — a list of rich
        renderables describing what will happen, plus the augmented
        mkvmerge command and a flag indicating whether any track was
        relabeled.
        """
        und_language = self._config.und_language
        if not und_language:
            return [], command, False

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

        return section, command, bool(relabel_lines)

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

        # Output the remuxed file to a temp tile, This will protect
        # the original file from been corrupted if anything goes wrong
        tmp_path = self.path.with_suffix(self.path.suffix + ".tmp")
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
            section, command, num_remove_ids = self._extend_track_command(
                track_type, command, num_remove_ids
            )
            manifest.extend(section)

        # Relabel und tracks if configured
        und_section, command, und_relabeled = self._extend_und_language_command(command)
        manifest.extend(und_section)

        command += [(str(self.path))]

        if not num_remove_ids and not und_relabeled:
            logger.info(f"\tAlready stripped {self.path}")
            self._reporter.stats.record_already_stripped()
            self._reporter.progress.mark_already_stripped()
            # Already in the desired state — let Walk write the timestamp
            # so subsequent runs short-circuit on the timestamp check.
            return True

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
        except Exception as exc:
            logger.error(str(exc))
            self._reporter.stats.record_error(self.path, str(exc))
            self._reporter.progress.mark_error()
            tmp_path.unlink(missing_ok=True)
        return changed
