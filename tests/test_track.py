"""Test Track class."""

import json

from nudebomb.track import Track

from .util import read

__all__ = ()


def _first_track_of_type(track_type: str) -> Track:
    """Select mockdata tracks by type instead of brittle array position."""
    tracks = json.loads(read("clean-tracks.json"))["tracks"]
    for data in tracks:
        if data["type"] == track_type:
            return Track(data)
    msg = f"no {track_type} track in mockdata"
    raise AssertionError(msg)


class TestTrack:
    """Test Track."""

    def test_video_track(self: "TestTrack") -> None:
        """Test video track."""
        track = _first_track_of_type("video")
        assert str(track) == "Track #0: und - MPEG-4p10/AVC/h.264"

    def test_audio_track(self: "TestTrack") -> None:
        """Test audio track."""
        track = _first_track_of_type("audio")
        assert str(track) == "Track #2: eng - AC-3"

    def test_subtitle_track(self: "TestTrack") -> None:
        """Test subtitle track."""
        track = _first_track_of_type("subtitles")
        assert str(track) == "Track #5: eng - SubRip/SRT"

    def test_id_is_str(self: "TestTrack") -> None:
        """Track ids are strings ready for command-line assembly."""
        track = _first_track_of_type("video")
        assert track.id == "0"
