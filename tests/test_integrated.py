"""Integration tests."""

import shutil
from pathlib import Path

from nudebomb.cli import main
from nudebomb.mkv import MKVFile

from .test_mkv import assert_eng_und_only
from .util import SRC_DIR, TEST_FN, mkv_tracks

TEST_DIR = Path("/tmp/nudebomb.test.integration")  # noqa
TEST_MKV = TEST_DIR / TEST_FN

__all__ = ()


class TestIntegrated:
    """Integrated tests."""

    def setup_method(self):
        """Set up tests."""
        shutil.rmtree(TEST_DIR, ignore_errors=True)
        TEST_DIR.mkdir()
        src_path = SRC_DIR / TEST_FN
        self.dest_path = TEST_DIR / TEST_FN
        shutil.copy(src_path, self.dest_path)
        self.src_tracks = mkv_tracks(self.dest_path)

    def teardown_method(self):
        """Tear down tests."""
        if TEST_DIR.exists():
            shutil.rmtree(TEST_DIR, ignore_errors=True)

    def test_dry_run(self):
        """Test dry run."""
        main(("nudebomb", "-l", "eng,und", "-d", str(self.dest_path)))
        out_tracks = mkv_tracks(self.dest_path)
        assert out_tracks == self.src_tracks

    def test_run(self):
        """Test run."""
        main(("nudebomb", "-l", "eng,und", "-r", str(TEST_DIR)))
        out_tracks = mkv_tracks(self.dest_path)
        assert_eng_und_only(out_tracks)

    def test_fail(self):
        """Test fail."""
        main(("nudebomb", "-l", "eng", str(TEST_DIR)))
        out_tracks = mkv_tracks(self.dest_path)
        assert out_tracks == self.src_tracks

    def test_strip_all_subs(self):
        """Test strib all subs."""
        main(("nudebomb", "-l", "eng,und", "-s", "''", "-S", "-U", "-r", str(TEST_DIR)))
        out_tracks = mkv_tracks(self.dest_path)
        for track in out_tracks:
            track_type = track.get("type")
            if track_type == MKVFile.SUBTITLE_TRACK_NAME:
                msg = f"subtitle track should not exist: {track}"
                raise AssertionError(msg)
