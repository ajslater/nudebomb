"""Tests for nudebomb doctor: config, options, CLI, and rendering."""

import shutil
from pathlib import Path
from unittest.mock import patch

import pytest
import tmdbsimple

from nudebomb.cli import get_arguments, main
from nudebomb.config import NudebombConfig
from nudebomb.doctor import (
    NudebombDoctor,
    _library_versions,
    environment_lines,
)
from tests.util import DOCTOR_KEY as KEY
from tests.util import SRC_PATH, doctor_config, run_doctor

# argparse's exit code for a usage error.
USAGE_ERROR = 2

__all__ = ()

pytestmark = pytest.mark.usefixtures("doctor_isolation")


class TestConfig:
    def test_env_vars(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("NUDEBOMB_NUDEBOMB__TMDB_API_KEY", "tmdb-env")
        monkeypatch.setenv("NUDEBOMB_NUDEBOMB__TVDB_API_KEY", "tvdb-env")
        monkeypatch.setenv("NUDEBOMB_NUDEBOMB__MKVMERGE_BIN", "/env/mkvmerge")
        config = doctor_config()
        assert config.tmdb_api_key == "tmdb-env"
        assert config.tvdb_api_key == "tvdb-env"
        assert config.mkvmerge_bin == "/env/mkvmerge"

    def test_no_languages(self) -> None:
        config = doctor_config()
        assert config.languages == frozenset()
        assert config.paths == ()

    def test_c_replaces_user_config(self, tmp_path: Path) -> None:
        user_config = tmp_path / "config" / "config.yaml"
        user_config.parent.mkdir()
        user_config.write_text(
            "nudebomb:\n  tmdb_api_key: user\n  mkvmerge_bin: /user/mkvmerge\n"
        )
        cli_config = tmp_path / "cli.yaml"
        cli_config.write_text(
            "nudebomb:\n  tmdb_api_key: cli\n  mkvmerge_bin: /cli/mkvmerge\n"
        )
        args = get_arguments(("nudebomb", "-c", str(cli_config)), doctor=True)
        config = NudebombConfig().get_doctor_config(args)
        assert config.tmdb_api_key == "cli"
        assert config.mkvmerge_bin == "/cli/mkvmerge"
        assert NudebombDoctor(args)._config_path() == cli_config
        lines = dict(environment_lines(cli_config))
        assert lines["config"].plain == f"found [{cli_config}]"

    def test_user_config_path(self, tmp_path: Path) -> None:
        args = get_arguments(("nudebomb",), doctor=True)
        path = NudebombDoctor(args)._config_path()
        assert path == tmp_path / "config" / "config.yaml"

    def test_missing_c(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code, out = run_doctor(capsys, "-c", str(tmp_path / "missing.yaml"))
        assert code == 1
        assert "Could not read config file" in out

    def test_library_versions(self) -> None:
        assert "treestamps 5.2" in _library_versions().plain
        with patch("nudebomb.doctor.requires", return_value=["not-a-dist>=1"]):
            assert _library_versions().plain == "not-a-dist not installed"


class TestRunOptions:
    def test_mkvmerge_bin(self, capsys: pytest.CaptureFixture[str]) -> None:
        code, out = run_doctor(capsys, "-b", "/nonexistent")
        assert code == 1
        assert "/nonexistent not found" in out

    def test_cli_key_beats_env(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.setenv("NUDEBOMB_NUDEBOMB__TMDB_API_KEY", "env-key")
        seen: list[str | None] = []

        def info(*_args, **_kwargs) -> dict:
            seen.append(tmdbsimple.API_KEY)
            return {}

        with patch.object(tmdbsimple.Configuration, "info", info):
            code, _ = run_doctor(capsys, "--tmdb-api-key", "cli-key")
        assert code == 0
        assert seen == ["cli-key"]

    def test_media_type_tv_drops_note(self, capsys: pytest.CaptureFixture[str]) -> None:
        with patch("tvdb_v4_official.TVDB"):
            _, movie = run_doctor(capsys, "--tvdb-api-key", KEY, "-m", "movie")
            _, tv = run_doctor(capsys, "--tvdb-api-key", KEY, "-m", "tv")
        assert "used only for media type 'tv'" in movie
        assert "used only for media type" not in tv
        assert KEY not in movie + tv

    def test_full_run_line_walks_nothing(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        media = tmp_path / "media"
        media.mkdir()
        mkv = media / "test.mkv"
        shutil.copy(SRC_PATH, mkv)
        mtime = mkv.stat().st_mtime_ns
        code, out = run_doctor(capsys, "-rl", "eng", "-t", "-m", "movie", str(media))
        assert code == 0
        assert mkv.stat().st_mtime_ns == mtime
        assert sorted(path.name for path in media.iterdir()) == ["test.mkv"]
        assert "Timestamps" in out

    def test_write_flags_ignored(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        media = tmp_path / "media"
        media.mkdir()
        out_file = tmp_path / "out.yaml"
        argv = ("-l", "eng", "-w", "-W", "--write-config-file", str(out_file))
        _, out = run_doctor(capsys, *argv, str(media))
        assert not (tmp_path / "config" / "config.yaml").exists()
        assert not (media / ".nudebomb.yaml").exists()
        assert not out_file.exists()
        for flag in ("-w/--write-config", "-W/--write-dir-config"):
            assert f"Ignoring {flag}" in out
        assert "Ignoring --write-config-file" in out


class TestParser:
    def test_bogus_option(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert run_doctor(capsys, "--bogus")[0] == USAGE_ERROR

    def test_help(self, capsys: pytest.CaptureFixture[str]) -> None:
        code, out = run_doctor(capsys, "-h")
        assert code == 0
        assert "nudebomb doctor" in out

    def test_bad_after(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert run_doctor(capsys, "-A", "notadate")[0] == 1


class TestProblemsOnly:
    def test_broken(self, capsys: pytest.CaptureFixture[str]) -> None:
        code, out = run_doctor(capsys, "-q", "-b", "/nonexistent")
        assert code == 1
        lines = out.splitlines()
        assert lines[:2] == [
            "Tools",
            "  FAIL  mkvmerge    /nonexistent not found (set mkvmerge_bin)",
        ]
        assert lines[-1] == "Summary: 0 ok, 0 warnings, 1 failed, 3 skipped."
        for absent in ("  ok  ", "  skip  ", "Online lookup", "Environment"):
            assert absent not in out

    def test_healthy_prints_nothing(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert run_doctor(capsys, "-q") == (0, "")

    def test_verbosity_from_env(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.setenv("NUDEBOMB_NUDEBOMB__VERBOSE", "0")
        assert run_doctor(capsys) == (0, "")
        code, out = run_doctor(capsys, "-v")
        assert code == 0
        assert "Environment" in out


class TestCLI:
    def test_doctor_exit_code(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert run_doctor(capsys)[0] == 0
        monkeypatch.setenv("NUDEBOMB_NUDEBOMB__MKVMERGE_BIN", "/nonexistent")
        assert run_doctor(capsys)[0] == 1

    def test_doctor_path_still_walks(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        monkeypatch.chdir(tmp_path)
        (tmp_path / "doctor").mkdir()
        main(("nudebomb", "-l", "eng", "./doctor"))
        assert "Skipping directory doctor" in capsys.readouterr().out

    def test_no_paths(self, capsys: pytest.CaptureFixture[str]) -> None:
        with pytest.raises(SystemExit) as exc_info:
            main(("nudebomb",))
        assert exc_info.value.code == USAGE_ERROR
        assert "required: path" in capsys.readouterr().err
