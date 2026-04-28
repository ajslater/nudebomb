"""MKV file operations."""

from __future__ import annotations

import json
import subprocess
import sys
from collections import defaultdict
from pathlib import Path
from typing import TYPE_CHECKING, Final

from loguru import logger

from nudebomb.langfiles import lang_to_alpha3
from nudebomb.log.reporter import Reporter
from nudebomb.track import Track

if TYPE_CHECKING:
    from confuse import AttrDict


class MKVFile:
    """Strips matroska files of unwanted audio and subtitles."""

    VIDEO_TRACK_NAME: Final = "video"
    AUDIO_TRACK_NAME: Final = "audio"
    SUBTITLE_TRACK_NAME: Final = "subtitles"
    REMOVABLE_TRACK_NAMES: Final = (AUDIO_TRACK_NAME, SUBTITLE_TRACK_NAME)

    def __init__(
        self, config: AttrDict, path: Path, reporter: Reporter | None = None
    ) -> None:
        """Initialize."""
        self._config: AttrDict = config
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
            logger.debug(f"\t{track_type}: {track.id} {track.lang}")
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
        output: str,
        command: list[str],
        num_remove_ids: int,
    ) -> tuple[str, list[str], int]:
        keep, remove = self._filtered_tracks(track_type)

        # Build the keep tracks options
        keep_ids = set()

        retaining_output = ""
        for count, track in enumerate(keep):
            keep_ids.add(str(track.id))
            retaining_output += f"   {track}\n"

            # Set the first track as default
            command += [
                "--default-track",
                ":".join((str(track.id), "0" if count else "1")),
            ]
        if retaining_output:
            output += f"Retaining {track_type} track(s):\n"
            output += retaining_output

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
            return output, command, num_remove_ids

        # Report what tracks will be removed
        remove_output = ""
        for track in remove:
            remove_output += f"   {track}\n"
        if remove_output:
            output += f"Removing {track_type} track(s):\n"
            output += remove_output

        output += "----------------------------\n"

        num_remove_ids += len(remove)

        return output, command, num_remove_ids

    @staticmethod
    def _remux_file(command: list[str]) -> None:
        """Remux a mkv file with the given parameters."""
        sys.stdout.write("Progress 0%")
        sys.stdout.flush()

        # Call command to remux file
        with subprocess.Popen(  # noqa: S603
            command,
            stdout=subprocess.PIPE,
            bufsize=1,
            text=True,
        ) as process:
            if process.stdout:
                for line in iter(process.stdout.readline, ""):
                    if "progress" in line.lower():
                        outline = f"\r{line.strip()}"
                        sys.stdout.write(outline)
                        sys.stdout.flush()
            print(flush=True)  # noqa: T201

            # Check if return code indicates an error
            if retcode := process.poll():
                kwargs = {}
                if process.stdout is not None:
                    kwargs["output"] = process.stdout
                raise subprocess.CalledProcessError(retcode, command, **kwargs)

    def _extend_und_language_command(
        self,
        output: str,
        command: list[str],
    ) -> tuple[str, list[str], bool]:
        """Add --language flags to relabel und tracks."""
        und_language = self._config.und_language
        if not und_language:
            return output, command, False

        relabeled = False
        relabel_output = ""
        for tracks in self._track_map.values():
            for track in tracks:
                if track.lang == "und":
                    command += ["--language", f"{track.id}:{und_language}"]
                    relabel_output += f"   {track} -> {und_language}\n"
                    relabeled = True
        if relabel_output:
            output += f"Relabeling 'und' track(s) to '{und_language}':\n"
            output += relabel_output
            output += "----------------------------\n"

        return output, command, relabeled

    def remove_tracks(self) -> bool:
        """Remove the unwanted tracks."""
        if not self._track_map:
            msg = f"not removing tracks from mkv with no tracks: {self.path}"
            logger.error(msg)
            self._reporter.stats.record_error(self.path, msg)
            self._reporter.progress.mark_error()
            return False
        logger.debug(f"Checking {self.path}:")
        # The command line args required to remux the mkv file
        output = f"\nRemuxing: {self.path}\n"
        output += "============================\n"

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

        # Iterate all tracks and mark which tracks are to be kept
        num_remove_ids = 0
        for track_type in self.REMOVABLE_TRACK_NAMES:
            output, command, num_remove_ids = self._extend_track_command(
                track_type, output, command, num_remove_ids
            )

        # Relabel und tracks if configured
        output, command, und_relabeled = self._extend_und_language_command(
            output, command
        )

        command += [(str(self.path))]

        if not num_remove_ids and not und_relabeled:
            logger.info(f"\tAlready stripped {self.path}")
            self._reporter.stats.record_already_stripped()
            self._reporter.progress.mark_already_stripped()
            return False

        changed = False
        try:
            logger.info(output)
            if self._config.dry_run:
                logger.info(f"\tNot remuxing on dry run {self.path}")
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
