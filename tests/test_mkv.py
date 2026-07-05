"""Test MKVFile object."""

import os
import shutil
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

from nudebomb.config import NudebombConfig
from nudebomb.log.reporter import Reporter
from nudebomb.log.summary import Stats
from nudebomb.mkv import MKVFile
from tests.util import SRC_PATH, TEST_FN, DiffTracksTest, mkv_tracks

if TYPE_CHECKING:
    from nudebomb.config import NudebombSettings

__all__ = ()

TEST_DIR = Path("/tmp/nudebomb.test_remux")  # noqa: S108
TEST_MKV = TEST_DIR / TEST_FN


def assert_eng_und_only(out_tracks: list[dict[str, str | dict[str, str]]]) -> None:
    """Asset english and undefined only tracks."""
    audio_count = 0
    subs_count = 0
    for track in out_tracks:
        track_type = track.get("type")
        if track_type not in MKVFile.REMOVABLE_TRACK_NAMES:
            continue
        lang = track["properties"]["language"]  # pyright: ignore[reportArgumentType], # ty: ignore[invalid-argument-type]
        print(track_type, lang)
        assert lang in ["und", "eng"]
        if track_type == MKVFile.SUBTITLE_TRACK_NAME:
            subs_count += 1
        elif track_type == MKVFile.AUDIO_TRACK_NAME:
            audio_count += 1
        else:
            msg = f"Bad track type: {track_type}"
            raise AssertionError(msg)
    assert audio_count == 2  # noqa: PLR2004
    assert subs_count == 2  # noqa: PLR2004


class TestMkv(DiffTracksTest):
    """Test MKV."""

    def setup_method(self) -> None:
        """Set up method."""
        shutil.rmtree(TEST_DIR, ignore_errors=True)
        TEST_DIR.mkdir()
        shutil.copy(SRC_PATH, TEST_MKV)
        self.src_tracks: list = mkv_tracks(TEST_MKV)  #  pyright: ignore[reportUninitializedInstanceVariable]
        os.environ["NUDEBOMB_NUDEBOMB__LANGUAGES__0"] = "und"
        os.environ["NUDEBOMB_NUDEBOMB__LANGUAGES__1"] = "eng"
        self._config: NudebombSettings = NudebombConfig().get_config()  #  pyright: ignore[reportUninitializedInstanceVariable]

    def teardown_method(self) -> None:
        """Tear down method."""
        shutil.rmtree(TEST_DIR)

    def test_dry_run(self) -> None:
        """Test dry run."""
        self._config.dry_run = True
        mkvfile = MKVFile(self._config, TEST_MKV)
        mkvfile.remove_tracks()
        out_tracks = mkv_tracks(TEST_MKV)
        self._diff_tracks(out_tracks)

    def test_run(self) -> None:
        """Test run."""
        mkvfile = MKVFile(self._config, TEST_MKV)
        mkvfile.remove_tracks()
        out_tracks = mkv_tracks(TEST_MKV)
        assert_eng_und_only(out_tracks)

    def test_already_stripped_returns_true(self) -> None:
        """
        A second pass over an already-stripped file still reports True.

        Walk relies on this to write a timestamp even when no remux was
        needed, so subsequent runs short-circuit on the timestamp check.
        """
        first = MKVFile(self._config, TEST_MKV)
        assert first.remove_tracks()

        second = MKVFile(self._config, TEST_MKV)
        assert second.remove_tracks()

    def test_fail(self) -> None:
        """Test fail."""
        self._config.languages = frozenset({"xxx"})
        mkvfile = MKVFile(self._config, TEST_MKV)
        mkvfile.remove_tracks()
        out_tracks = mkv_tracks(TEST_MKV)
        self._diff_tracks(out_tracks)

    def test_missing_file_records_error(self) -> None:
        """A file mkvmerge cannot identify records an error, not a crash."""
        stats = Stats()
        reporter = Reporter(stats=stats)
        mkvfile = MKVFile(self._config, TEST_DIR / "missing.mkv", reporter)
        assert not mkvfile.remove_tracks()
        assert stats.errors

    def test_garbage_file_records_and_continues(self) -> None:
        """A non-matroska file is recorded and skipped, not fatal."""
        garbage = TEST_DIR / "garbage.mkv"
        garbage.write_bytes(b"not a matroska file")
        stats = Stats()
        reporter = Reporter(stats=stats)
        mkvfile = MKVFile(self._config, garbage, reporter)
        assert not mkvfile.remove_tracks()
        assert stats.errors or stats.warnings

    def test_warning_marks_progress(self) -> None:
        """Warnings push the documented '!' mark onto the progress bar."""
        garbage = TEST_DIR / "warn.mkv"
        garbage.write_bytes(b"not a matroska file")
        reporter = Reporter(stats=Stats(), progress=MagicMock())  # pyright: ignore[reportArgumentType]
        MKVFile(self._config, garbage, reporter)
        assert reporter.progress.mark_warning.called  # pyright: ignore[reportAttributeAccessIssue], # ty: ignore[unresolved-attribute]

    def test_stale_tmp_removed(self) -> None:
        """A leftover .tmp from a killed run is cleaned up on the next pass."""
        tmp = TEST_MKV.with_suffix(TEST_MKV.suffix + ".tmp")
        tmp.write_bytes(b"stale")
        self._config.dry_run = True
        mkvfile = MKVFile(self._config, TEST_MKV)
        mkvfile.remove_tracks()
        assert not tmp.exists()
