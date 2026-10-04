"""Tests for the nudebomb doctor timestamps report."""

import time
from pathlib import Path

import pytest
from treestamps import Grovestamps, Treestamps

from nudebomb.cli import get_arguments
from nudebomb.config import NudebombConfig
from nudebomb.doctor import FAIL, OK, SKIP, WARN, CheckResult, _age, check_timestamps
from nudebomb.walk import build_grove_config
from tests.util import doctor_config, run_doctor

STAMP_FILE = ".nudebomb_treestamps.yaml"

__all__ = ()

pytestmark = pytest.mark.usefixtures("doctor_isolation")


class TestTimestamps:
    @staticmethod
    def _media(tmp_path: Path) -> Path:
        media = tmp_path / "media"
        media.mkdir(exist_ok=True)
        (media / "a.mkv").write_bytes(b"")
        return media

    @staticmethod
    def _record(media: Path, *, dump: bool = True) -> None:
        """Write timestamps as a ``-rtl eng`` run would."""
        args = get_arguments(("nudebomb", "-rtl", "eng", str(media)))
        grove = Grovestamps(build_grove_config(NudebombConfig().get_config(args)))
        grove.set(Treestamps.get_dir(media), media / "a.mkv")
        if dump:
            grove.dumpf()

    @staticmethod
    def _check(media: Path, *argv: str) -> list[CheckResult]:
        return check_timestamps(doctor_config("-rtl", "eng", *argv, str(media)))

    def test_no_paths_no_section(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert check_timestamps(doctor_config()) == []
        _, out = run_doctor(capsys)
        assert "Timestamps" not in out

    def test_none_recorded(self, tmp_path: Path) -> None:
        media = self._media(tmp_path)
        assert self._check(media) == [
            CheckResult(str(media), SKIP, "no timestamps recorded")
        ]

    def test_recorded(self, tmp_path: Path) -> None:
        media = self._media(tmp_path)
        self._record(media)
        (result,) = self._check(media)
        assert result.status == OK
        assert result.detail == "1 entry, written just now"
        assert not result.path

    @pytest.mark.parametrize(
        ("argv", "dir_config", "label"),
        [
            pytest.param(("-l", "fra"), "", "languages", id="languages"),
            pytest.param(
                (),
                "nudebomb:\n  title: false\n",
                ".nudebomb.yaml contents",
                id="dir-config",
            ),
        ],
    )
    def test_config_changed(
        self, tmp_path: Path, argv: tuple[str, ...], dir_config: str, label: str
    ) -> None:
        media = self._media(tmp_path)
        self._record(media)
        if dir_config:
            (media / ".nudebomb.yaml").write_text(dir_config)
        (result,) = self._check(media, *argv)
        assert result.status == WARN
        assert result.detail == f"next run discards it (config changed: {label})"

    def test_no_check_config(self, tmp_path: Path) -> None:
        media = self._media(tmp_path)
        self._record(media)
        (result,) = self._check(media, "-C", "-l", "fra")
        assert result.status == OK
        assert result.detail.endswith("; config differs (languages), ignored by -C")

    def test_leftover_wal(self, tmp_path: Path) -> None:
        media = self._media(tmp_path)
        self._record(media, dump=False)
        (result,) = self._check(media)
        assert result.status == WARN
        assert result.detail == (
            "leftover WAL from an interrupted run (1 entry); the next run replays it"
        )

    def test_corrupt_snapshot(self, tmp_path: Path) -> None:
        media = self._media(tmp_path)
        (media / STAMP_FILE).write_text(":\n  - [")
        (result,) = self._check(media)
        assert result.status == WARN
        assert result.detail.startswith("next run discards it (")
        assert "Error" in result.detail

    def test_one_row_per_root(self, tmp_path: Path) -> None:
        media = self._media(tmp_path)
        (media / "b.mkv").write_bytes(b"")
        results = check_timestamps(
            doctor_config("-l", "eng", str(media / "a.mkv"), str(media / "b.mkv"))
        )
        assert [result.name for result in results] == [str(media)]

    def test_missing_path(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        missing = tmp_path / "missing"
        assert self._check(missing) == [
            CheckResult(str(missing), FAIL, "does not exist")
        ]
        code, out = run_doctor(capsys, "-l", "eng", str(missing))
        assert code == 1
        assert "1 failed" in out

    def test_writes_nothing(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        media = self._media(tmp_path)
        run_doctor(capsys, "-rtl", "eng", str(media))
        assert sorted(path.name for path in media.iterdir()) == ["a.mkv"]

    @pytest.mark.parametrize(
        ("seconds", "expected"),
        [
            (5, "just now"),
            (60, "1 minute ago"),
            (2 * 3600 + 5, "2 hours ago"),
            (3 * 86400 + 5, "3 days ago"),
        ],
    )
    def test_age(self, seconds: int, expected: str) -> None:
        assert _age(time.time() - seconds) == expected
