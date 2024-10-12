"""MKV file operations."""

import json
import subprocess
import sys
import time
from pathlib import Path

from termcolor import cprint

from nudebomb.langfiles import lang_to_alpha3
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
        tracks = json_data.get("tracks")
        if not tracks:
            cprint(
                f"WARNING: No tracks for {self.path}. Might not be a valid movie.",
                "yellow",
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
            if self._config.verbose:
                cprint(
                    f"\t{track_type}: {track.id} {track.lang}", "white", attrs=["dark"]
                )
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

        output += f"Retaining {track_type} track(s):\n"
        for count, track in enumerate(keep):
            keep_ids.add(str(track.id))
            output += f"   {track}\n"

            # Set the first track as default
            command += [
                "--default-track",
                ":".join((str(track.id), "0" if count else "1")),
            ]

        # Set which tracks are to be kept
        if keep_ids:
            prefix = track_type
            if track_type == self.SUBTITLE_TRACK_NAME:
                prefix = prefix[:-1]
            command += [f"--{prefix}-tracks", ",".join(sorted(keep_ids))]
        elif track_type == self.SUBTITLE_TRACK_NAME:
            command += ["--no-subtitles"]
        else:
            reason = "Tried to remove all audio tracks."
            raise ValueError(reason)

        # Report what tracks will be removed
        output += f"Removing {track_type} track(s):\n"
        for track in remove:
            output += f"   {track}\n"

        output += "----------------------------\n"

        num_remove_ids += len(remove)

        return output, command, num_remove_ids

    @staticmethod
    def _remux_file(command):
        """Remux a mkv file with the given parameters."""
        sys.stdout.write("Progress 0%")
        sys.stdout.flush()

        # Call subprocess command to remux file
        process = subprocess.Popen(  # noqa: S603
            command,
            stdout=subprocess.PIPE,
            text=True,
        )
        # Display Percentage until subprocess has finished
        while process.poll() is None:
            # Sleep for a quarter second and then display progress
            # TODO replace with communicate timeout wait
            time.sleep(0.25)
            if process.stdout:
                for line in iter(process.stdout.readline, ""):
                    if "progress" in line.lower():
                        sys.stdout.write(f"\r{line.strip()}")
                        sys.stdout.flush()
        sys.stdout.write("\n")

        # Check if return code indicates an error
        if retcode := process.poll():
            kwargs = {}
            if process.stdout is not None:
                kwargs["output"] = process.stdout
            raise subprocess.CalledProcessError(retcode, command, **kwargs)

    def remove_tracks(self):
        """Remove the unwanted tracks."""
        if self._config.verbose:
            cprint(f"Checking {self.path}:", "white", attrs=["dark"])
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
            if self._config.verbose:
                cprint(f"\tAlready stripped {self.path}", "green", attrs=["dark"])
            else:
                cprint(".", "green", attrs=["bold"], end="")
            return

        try:
            cprint(output, flush=True)
            if self._config.dry_run:
                cprint("\tNot remuxing on dry run {self.path}", "black", attrs=["bold"])
            else:
                self._remux_file(command)
                tmp_path.replace(self.path)
        except Exception as exc:
            cprint(str(exc), "red")
            tmp_path.unlink(missing_ok=True)
