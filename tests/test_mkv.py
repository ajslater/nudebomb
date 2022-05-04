"""Test MKVFile object."""
import os
import shutil

from pathlib import Path

from nudebomb.config import get_config
from nudebomb.mkv import MKVFile

from .util import SRC_PATH, TEST_FN, mkv_tracks


__all__ = ()

TEST_DIR = Path("/tmp/nudebomb.test_remux")
TEST_MKV = TEST_DIR / TEST_FN


def assert_eng_und_only(out_tracks):
    audio_count = 0
    subs_count = 0
    for track in out_tracks:
        track_type = track.get("type")
        if track_type not in MKVFile.REMOVABLE_TRACK_NAMES:
            continue
        lang = track["properties"]["language"]
        print(track_type, lang)
        assert lang in ["und", "eng"]
        if track_type == MKVFile.SUBTITLE_TRACK_NAME:
            subs_count += 1
        elif track_type == MKVFile.AUDIO_TRACK_NAME:
            audio_count += 1
        else:
            raise AssertionError(f"Bad track type: {track_type}")
    assert audio_count == 2
    assert subs_count == 2


class TestMkv:
    def setup_method(self):
        shutil.rmtree(TEST_DIR, ignore_errors=True)
        TEST_DIR.mkdir()
        shutil.copy(SRC_PATH, TEST_MKV)
        self.src_tracks = mkv_tracks(TEST_MKV)
        os.environ["NUDEBOMB_NUDEBOMB__LANGUAGES__0"] = "und"
        os.environ["NUDEBOMB_NUDEBOMB__LANGUAGES__1"] = "eng"

    def teardown_method(self):
        shutil.rmtree(TEST_DIR)

    def test_dry_run(self):
        config = get_config()
        config.dry_run = True
        mkvfile = MKVFile(config, TEST_MKV)
        mkvfile.remove_tracks()
        out_tracks = mkv_tracks(TEST_MKV)

        assert out_tracks == self.src_tracks

    def test_run(self):
        config = get_config()
        mkvfile = MKVFile(config, TEST_MKV)
        mkvfile.remove_tracks()
        out_tracks = mkv_tracks(TEST_MKV)
        assert_eng_und_only(out_tracks)

    def test_fail(self):
        config = get_config()
        config.languages = ["xxx"]
        mkvfile = MKVFile(config, TEST_MKV)
        mkvfile.remove_tracks()
        out_tracks = mkv_tracks(TEST_MKV)

        assert out_tracks == self.src_tracks
