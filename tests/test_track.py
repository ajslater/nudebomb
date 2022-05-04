"""Test Track class."""
import json

from nudebomb.track import Track

from .util import read


__all__ = ()


class TestTrack:
    def test_video_track(self):
        data = json.loads(read("clean_tracks.json"))["tracks"][0]
        track = Track(data)
        assert str(track) == "Track #0: und - MPEG-4p10/AVC/h.264"

    def test_audio_track(self):
        data = json.loads(read("clean_tracks.json"))["tracks"][1]
        track = Track(data)
        assert str(track) == "Track #2: eng - AC-3"

    def test_subtitle_track(self):
        data = json.loads(read("clean_tracks.json"))["tracks"][2]
        track = Track(data)
        assert str(track) == "Track #5: eng - SubRip/SRT"
