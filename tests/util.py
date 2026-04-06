"""Common test utilities."""

import json
import subprocess
from pathlib import Path

from deepdiff import DeepDiff

TEST_FN = "test5.mkv"
SRC_DIR = Path("tests/test_files")
SRC_PATH = SRC_DIR / TEST_FN

__all__ = ()


def mkv_tracks(path: Path) -> list:
    """Get tracks from mkv."""
    cmd = ("mkvmerge", "-J", str(path))
    proc = subprocess.run(cmd, check=True, capture_output=True, text=True)  # noqa: S603
    data = json.loads(proc.stdout)
    return data.get("tracks")


def read(filename: str) -> bytes:
    """Open data file and return contents."""
    path = Path(__file__).parent / "mockdata" / filename
    return path.read_bytes()


class DiffTracksTest:
    def _diff_tracks(
        self,
        out_tracks: list[dict[str, dict[str, bool] | int]],
    ) -> None:
        diff = DeepDiff(self.src_tracks, out_tracks)  # pyright: ignore[reportAttributeAccessIssue], # ty: ignore[unresolved-attribute]
        if diff:
            print(diff)
        assert not diff
