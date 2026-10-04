"""Tests for the nudebomb doctor dependency checks."""

import os
import shutil
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch
from urllib.error import URLError

import pytest
import tmdbsimple
from requests.exceptions import ConnectionError as RequestsConnectionError
from requests.exceptions import HTTPError, ReadTimeout
from requests.models import Response

from nudebomb.config import NudebombSettings
from nudebomb.doctor import (
    FAIL,
    OK,
    SKIP,
    WARN,
    CheckResult,
    check_cache,
    check_mkvmerge,
    check_tmdb,
    check_tvdb,
)
from tests.util import DOCTOR_KEY as KEY
from tests.util import doctor_config

__all__ = ()

pytestmark = pytest.mark.usefixtures("doctor_isolation")


def _http_error(status: int, message: str = "") -> HTTPError:
    response = Response()
    response.status_code = status
    exc = HTTPError(message)
    exc.response = response
    return exc


class TestMkvmerge:
    def test_found(self) -> None:
        result = check_mkvmerge("mkvmerge")
        assert result.status == OK
        assert result.version.startswith("v")
        assert result.path == shutil.which("mkvmerge")

    def test_missing_path_has_install_hint(self) -> None:
        with patch("nudebomb.doctor._detect_pkg_manager", return_value="apt"):
            result = check_mkvmerge("/nonexistent/mkvmerge")
        assert result.status == FAIL
        assert result.detail == "/nonexistent/mkvmerge not found (set mkvmerge_bin)"
        assert result.hint == "apt install mkvtoolnix"

    def test_missing_bare_name(self) -> None:
        result = check_mkvmerge("mkvmerge-not-installed")
        assert result.status == FAIL
        assert result.detail == (
            "'mkvmerge-not-installed' not found on PATH (set mkvmerge_bin)"
        )

    def test_nonzero_exit(self) -> None:
        proc = subprocess.CompletedProcess((), returncode=3, stdout="", stderr="")
        with patch("nudebomb.doctor.subprocess.run", return_value=proc):
            result = check_mkvmerge(sys.executable)
        assert result.status == FAIL
        assert result.detail == "--version exited with code 3"
        assert result.path == shutil.which(sys.executable)

    def test_timeout(self) -> None:
        timeout = subprocess.TimeoutExpired("mkvmerge", 10)
        with patch("nudebomb.doctor.subprocess.run", side_effect=timeout):
            result = check_mkvmerge(sys.executable)
        assert result.status == FAIL
        assert "timed out" in result.detail

    def test_unparsed_version_line(self) -> None:
        proc = subprocess.CompletedProcess((), 0, stdout="something else\n")
        with patch("nudebomb.doctor.subprocess.run", return_value=proc):
            result = check_mkvmerge(sys.executable)
        assert result.status == OK
        assert result.detail == "something else"
        assert not result.version


class TestTMDB:
    def test_no_key(self) -> None:
        assert check_tmdb(None).status == SKIP

    def test_accepted_with_given_key(self) -> None:
        seen: list[str | None] = []

        def info(*_args, **_kwargs) -> dict:
            seen.append(tmdbsimple.API_KEY)
            return {}

        with patch.object(tmdbsimple.Configuration, "info", info):
            result = check_tmdb(KEY)
        assert result == CheckResult("TMDB", OK, "API key accepted")
        assert seen == [KEY]

    @pytest.mark.parametrize(
        ("exc", "status", "detail"),
        [
            pytest.param(
                _http_error(401), FAIL, "API key rejected (HTTP 401)", id="401"
            ),
            pytest.param(_http_error(429), WARN, "rate limited", id="429"),
            pytest.param(
                _http_error(500, f"500 Server Error for url: /3?api_key={KEY}"),
                FAIL,
                "HTTP 500",
                id="500",
            ),
            pytest.param(
                RequestsConnectionError(f"Max retries: /3?api_key={KEY}"),
                FAIL,
                "unreachable: Max retries: /3?api_key=REDACTED",
                id="connection",
            ),
            pytest.param(ReadTimeout("read timed out"), FAIL, "unreachable", id="read"),
            pytest.param(ValueError(KEY), FAIL, "ValueError: REDACTED", id="other"),
        ],
    )
    def test_errors(self, exc: Exception, status: str, detail: str) -> None:
        with patch.object(tmdbsimple.Configuration, "info", side_effect=exc):
            result = check_tmdb(KEY)
        assert result.status == status
        assert result.detail.startswith(detail)
        assert KEY not in result.detail


class TestTVDB:
    def test_no_key(self) -> None:
        assert check_tvdb(None, "tv").status == SKIP

    def test_accepted_notes_media_type(self) -> None:
        with patch("tvdb_v4_official.TVDB") as tvdb:
            result = check_tvdb(KEY, None)
        tvdb.assert_called_once_with(KEY)
        assert result.status == OK
        assert result.detail == "API key accepted (used only for media type 'tv')"

    def test_accepted_tv_has_no_note(self) -> None:
        with patch("tvdb_v4_official.TVDB"):
            result = check_tvdb(KEY, "tv")
        assert result.detail == "API key accepted"

    @pytest.mark.parametrize(
        ("exc", "detail"),
        [
            pytest.param(
                Exception("Code:HTTP Error 401: Unauthorized, InvalidAPIKey"),
                "Code:HTTP Error 401: Unauthorized, InvalidAPIKey",
                id="rejected",
            ),
            pytest.param(
                URLError("no network"),
                "unreachable: <urlopen error no network>",
                id="unreachable",
            ),
            pytest.param(KeyError("data"), "KeyError: 'data'", id="bad-body"),
            pytest.param(Exception(f"bad key {KEY}"), "bad key REDACTED", id="scrub"),
        ],
    )
    def test_errors(self, exc: Exception, detail: str) -> None:
        with patch("tvdb_v4_official.TVDB", side_effect=exc):
            result = check_tvdb(KEY, "tv")
        assert result.status == FAIL
        assert result.detail == detail


class TestCache:
    @staticmethod
    def _config(**kwargs: str) -> NudebombSettings:
        config = doctor_config()
        for key, value in kwargs.items():
            setattr(config, key, value)
        return config

    def test_skip_without_keys(self) -> None:
        assert check_cache(self._config()).status == SKIP

    def test_writable_counts_entries(self, tmp_path: Path) -> None:
        ids = tmp_path / "cache" / "movie" / "ids"
        ids.mkdir(parents=True)
        (ids / "tmdb_1.json").write_text("{}")
        (ids.parent / "foo.json").write_text("{}")
        result = check_cache(self._config(tmdb_api_key=KEY))
        assert result == CheckResult(
            "cache", OK, "writable, 2 entries", path=str(tmp_path / "cache")
        )

    def test_missing_will_be_created_and_is_not(self, tmp_path: Path) -> None:
        result = check_cache(self._config(tvdb_api_key=KEY))
        assert result.status == OK
        assert result.detail == "will be created"
        assert not (tmp_path / "cache").exists()

    @pytest.mark.skipif(
        sys.platform == "win32" or os.geteuid() == 0,
        reason="needs POSIX permissions that apply",
    )
    @pytest.mark.parametrize(
        ("subdir", "detail"),
        [("", "not writable"), ("cache", "cannot be created")],
        ids=("existing", "missing"),
    )
    def test_read_only(self, tmp_path: Path, subdir: str, detail: str) -> None:
        cache = tmp_path / "cache"
        locked = cache if not subdir else tmp_path / "locked"
        locked.mkdir()
        if subdir:
            cache = locked / subdir
        locked.chmod(0o500)
        try:
            with patch("nudebomb.doctor.user_cache_dir", lambda _prog: str(cache)):
                result = check_cache(self._config(tmdb_api_key=KEY))
        finally:
            locked.chmod(0o700)
        assert result.status == FAIL
        assert result.detail == detail
