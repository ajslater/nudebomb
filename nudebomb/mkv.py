"""MKV file operations."""

import json
import subprocess
import sys
from pathlib import Path

from nudebomb.langfiles import lang_to_alpha3
from nudebomb.printer import Printer
from nudebomb.track import Track


class MKVFile:
    """Strips matroska files of unwanted audio and subtitles."""

    VIDEO_TRACK_NAME = "video"
    AUDIO_TRACK_NAME = "audio"
    SUBTITLE_TRACK_NAME = "subtitles"
    REMOVABLE_TRACK_NAMES = (AUDIO_TRACK_NAME, SUBTITLE_TRACK_NAME)

    def __init__(self, config, path):
        """Initialize."""
        self._config = config
        self.path = Path(path)
        self._printer = Printer(self._config.verbose)
        self._init_track_map()

    def _init_track_map(self):
        self._track_map = {}

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
                self._printer.error(error)
        if warnings := json_data.get("warnings"):
            for warning in warnings:
                self._printer.warn(warning)
        tracks = json_data.get("tracks")
        if not tracks:
            self._printer.warn(
                f"No tracks. Might not be a valid matroshka video file: {self.path}",
            )
            return

        # load into our map.
        for track_data in tracks:
            track_obj = Track(track_data)
            if track_obj.type not in self._track_map:
                self._track_map[track_obj.type] = []
            self._track_map[track_obj.type].append(track_obj)

    def _filtered_tracks(self, track_type):
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
            self._printer.extra_info(f"\t{track_type}: {track.id} {track.lang}")
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

    def _extend_track_command(self, track_type, output, command, num_remove_ids):
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
            self._printer.warn(f"No tracks to remove from {self.path}")
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
    def _remux_file(command):
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

    def remove_tracks(self):
        """Remove the unwanted tracks."""
        if not self._track_map:
            self._printer.error(
                f"not removing tracks from mkv with no tracks: {self.path}",
            )
            return
        self._printer.extra_info(f"Checking {self.path}:")
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
        command += [(str(self.path))]

        if not num_remove_ids:
            self._printer.skip_timestamp(f"\tAlready stripped {self.path}")
            return

        try:
            self._printer.work_manifest(output)
            if self._config.dry_run:
                self._printer.dry_run("\tNot remuxing on dry run {self.path}")
            else:
                self._remux_file(command)
                tmp_path.replace(self.path)
        except Exception as exc:
            self._printer.error("", exc)
            tmp_path.unlink(missing_ok=True)
