"""Common test utilities."""

import json
import subprocess
from pathlib import Path

import pytest
from deepdiff import DeepDiff

from nudebomb.cli import get_arguments, main
from nudebomb.config import NudebombConfig, NudebombSettings

TEST_FN = "test5.mkv"
SRC_DIR = Path("tests/test_files")
SRC_PATH = SRC_DIR / TEST_FN
# A fake API key; doctor output must never contain it.
DOCTOR_KEY = "sekrit-key-1234"

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


def doctor_config(*argv: str) -> NudebombSettings:
    """Resolve config through the doctor parser."""
    args = get_arguments(("nudebomb", *argv), doctor=True)
    return NudebombConfig().get_doctor_config(args)


def run_doctor(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, str]:
    """Run ``nudebomb doctor`` through main; return the exit code and output."""
    with pytest.raises(SystemExit) as exc_info:
        main(("nudebomb", "doctor", *argv))
    captured = capsys.readouterr()
    code = exc_info.value.code
    return code if isinstance(code, int) else 0, captured.out + captured.err
