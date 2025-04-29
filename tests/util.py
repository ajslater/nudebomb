"""Common test utilities."""

import json
import subprocess
from pathlib import Path

from deepdiff import DeepDiff

TEST_FN = "test5.mkv"
SRC_DIR = Path("tests/test_files")
SRC_PATH = SRC_DIR / TEST_FN

__all__ = ()


def mkv_tracks(path):
    """Get tracks from mkv."""
    cmd = ("mkvmerge", "-J", str(path))
    proc = subprocess.run(cmd, check=True, capture_output=True, text=True)  # noqa: S603
    data = json.loads(proc.stdout)
    return data.get("tracks")


def read(filename):
    """Open data file and return contents."""
    path = Path(__file__).parent / "mockdata" / filename
    with path.open("r") as stream:
        return stream.read()


class DiffTracksTest:
    def _diff_tracks(self, out_tracks):
        diff = DeepDiff(self.src_tracks, out_tracks)  # type: ignore[reportAttributeAccessIssue]
        if diff:
            print(diff)  # noqa: T201
        assert not diff
