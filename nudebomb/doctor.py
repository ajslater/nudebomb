"""
``nudebomb doctor``: report on nudebomb's external dependencies.

Checks mkvmerge, the TMDB and TVDB API keys, the lookup cache directory and,
for any paths given, what the next run would make of their timestamp files.
Read-only: it walks, remuxes, and writes nothing. Modeled on ``picopt doctor``.
"""

from __future__ import annotations

import os
import platform
import re
import shutil
import subprocess
import sys
import time
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, replace
from http import HTTPStatus
from importlib.metadata import PackageNotFoundError, requires, version
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, Final, Never, TypeAlias

import tmdbsimple as tmdb
from confuse import Configuration
from loguru import logger
from platformdirs import user_cache_dir
from requests.exceptions import HTTPError, RequestException
from rich.table import Table
from rich.text import Text
from treestamps import Grovestamps

from nudebomb.config import NudebombConfig
from nudebomb.log import console
from nudebomb.log import setup as setup_logging
from nudebomb.log.styles import (
    DOCTOR_COMMAND,
    DOCTOR_DETAIL_STYLES,
    DOCTOR_HINT,
    DOCTOR_LABEL,
    DOCTOR_NAME,
    DOCTOR_PATH,
    DOCTOR_SECTION,
    DOCTOR_STATUS_MARKS,
    DOCTOR_SUMMARY,
    DOCTOR_VERSION,
    DoctorStatus,
)
from nudebomb.lookup import MediaType
from nudebomb.lookup.tmdb import configure_tmdb
from nudebomb.lookup.tvdb import connect_tvdb
from nudebomb.lookup.util import redact_api_key
from nudebomb.version import PROGRAM_NAME, VERSION
from nudebomb.walk import build_grove_config

if TYPE_CHECKING:
    from argparse import Namespace
    from collections.abc import Iterable

    from rich.console import Console
    from treestamps import StampFileReport, TreestampsReport

    from nudebomb.config import NudebombSettings

OK: Final = DoctorStatus.OK
WARN: Final = DoctorStatus.WARN
FAIL: Final = DoctorStatus.FAIL
SKIP: Final = DoctorStatus.SKIP
_PROBLEMS: Final = frozenset({WARN, FAIL})

_VERSION_TIMEOUT_SECONDS: Final = 10
_NO_KEY: Final = "no API key configured"
_KEY_ACCEPTED: Final = "API key accepted"
_LEFTOVER_WAL: Final = "leftover WAL from an interrupted run"
_MKVMERGE_VERSION: Final = re.compile(r"mkvmerge\s+(v\S+)\s*(.*)")
# The leading distribution name of a requirement string like "rich~=15.0".
_REQUIREMENT_NAME: Final = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
_TIME_UNITS: Final = (("day", 86400), ("hour", 3600), ("minute", 60))
# Environment labels and check tags + names share this width (the tag is 4
# wide plus a 2 wide gap), so details start in the same column everywhere.
_LABEL_WIDTH: Final = 16
_NAME_WIDTH: Final = _LABEL_WIDTH - 6

# ── mkvmerge install hints, keyed by package manager as picopt does ──

_BREW: Final = "brew"
_APT: Final = "apt"
_DNF: Final = "dnf"
_WINDOWS: Final = "windows"
_MKVTOOLNIX_HINTS: Final = MappingProxyType(
    {
        _BREW: "brew install mkvtoolnix",
        _APT: "apt install mkvtoolnix",
        _DNF: "dnf install mkvtoolnix",
        _WINDOWS: "https://mkvtoolnix.download/",
    }
)


def _linux_pkg_manager() -> str:
    try:
        info = Path("/etc/os-release").read_text().lower()
    except OSError:
        return ""
    if "debian" in info or "ubuntu" in info:
        return _APT
    if "fedora" in info or "rhel" in info or "centos" in info:
        return _DNF
    return ""


def _detect_pkg_manager() -> str:
    match platform.system():
        case "Darwin":
            return _BREW
        case "Windows":
            return _WINDOWS
        case "Linux":
            return _linux_pkg_manager()
        case _:
            return ""


# ── Checks ──


@dataclass(frozen=True, slots=True)
class CheckResult:
    """One line of the report; each part gets its own color."""

    name: str
    status: DoctorStatus
    detail: str
    version: str = ""
    path: str = ""
    hint: str = ""


def _plural(count: int, word: str, plural: str = "") -> str:
    return f"{count} {word if count == 1 else plural or word + 's'}"


def _describe(exc: Exception) -> str:
    """Exception text, prefixed with its type unless it's a bare Exception."""
    return str(exc) if type(exc) is Exception else f"{type(exc).__name__}: {exc}"


def _scrub(text: str, api_key: str) -> str:
    """Remove the key from text that will be printed."""
    # requests puts the full URL, api_key= included, in HTTPError text.
    return redact_api_key(text).replace(api_key, "REDACTED")


def _mkvmerge_fail(detail: str, path: str = "") -> CheckResult:
    hint = _MKVTOOLNIX_HINTS.get(_detect_pkg_manager(), "")
    return CheckResult("mkvmerge", FAIL, detail, path=path, hint=hint)


def _mkvmerge_not_found(mkvmerge_bin: str) -> CheckResult:
    # Like which(), treat a name with a directory part as a path.
    if any(sep in mkvmerge_bin for sep in (os.sep, os.altsep) if sep):
        detail = f"{mkvmerge_bin} not found"
    else:
        detail = f"'{mkvmerge_bin}' not found on PATH"
    return _mkvmerge_fail(f"{detail} (set mkvmerge_bin)")


def check_mkvmerge(mkvmerge_bin: str) -> CheckResult:
    """Find mkvmerge and report its version."""
    if (path := shutil.which(mkvmerge_bin)) is None:
        return _mkvmerge_not_found(mkvmerge_bin)
    try:
        proc = subprocess.run(  # noqa: S603
            (path, "--version"),
            capture_output=True,
            text=True,
            errors="replace",
            check=False,
            timeout=_VERSION_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        detail = f"--version timed out after {_VERSION_TIMEOUT_SECONDS}s"
        return _mkvmerge_fail(detail, path)
    except OSError as exc:
        return _mkvmerge_fail(f"could not run: {exc}", path)
    if proc.returncode:
        return _mkvmerge_fail(f"--version exited with code {proc.returncode}", path)
    first_line = next(iter(proc.stdout.splitlines()), "").strip()
    if match := _MKVMERGE_VERSION.match(first_line):
        mkvmerge_version, detail = match[1], match[2]
    else:
        mkvmerge_version, detail = "", first_line
    return CheckResult("mkvmerge", OK, detail, version=mkvmerge_version, path=path)


def _tmdb_http_error(exc: HTTPError) -> tuple[DoctorStatus, str]:
    status_code = exc.response.status_code if exc.response is not None else None
    match status_code:
        case HTTPStatus.UNAUTHORIZED:
            return FAIL, "API key rejected (HTTP 401)"
        case HTTPStatus.TOO_MANY_REQUESTS:
            return WARN, "rate limited (HTTP 429), try again later"
        case None:
            return FAIL, str(exc)
        case _:
            return FAIL, f"HTTP {status_code}"


def check_tmdb(api_key: str | None) -> CheckResult:
    """Make one authenticated, read-only TMDB request."""
    if not api_key:
        return CheckResult("TMDB", SKIP, _NO_KEY)
    configure_tmdb(api_key)
    try:
        tmdb.Configuration().info()
    except HTTPError as exc:
        status, detail = _tmdb_http_error(exc)
    except RequestException as exc:
        # Not ConnectionError alone: a stalled read raises ReadTimeout.
        status, detail = FAIL, f"unreachable: {exc}"
    except Exception as exc:
        status, detail = FAIL, _describe(exc)
    else:
        status, detail = OK, _KEY_ACCEPTED
    return CheckResult("TMDB", status, _scrub(detail, api_key))


def check_tvdb(api_key: str | None, media_type: str | None) -> CheckResult:
    """Log in to TVDB, as a run does on its first TVDB query."""
    if not api_key:
        return CheckResult("TVDB", SKIP, _NO_KEY)
    try:
        connect_tvdb(api_key)
    except OSError as exc:
        # URLError and socket timeouts.
        status, detail = FAIL, f"unreachable: {exc}"
    except Exception as exc:
        # A rejected key is a bare Exception("Code:HTTP Error 401: …").
        status, detail = FAIL, _describe(exc)
    else:
        status, detail = OK, _KEY_ACCEPTED
        if media_type != MediaType.TV:
            detail += f" (used only for media type '{MediaType.TV}')"
    return CheckResult("TVDB", status, _scrub(detail, api_key))


def _count_cache_entries(cache_dir: Path) -> str:
    try:
        count = sum(1 for _ in cache_dir.rglob("*.json"))
    except OSError:
        return ""
    return f", {_plural(count, 'entry', 'entries')}"


def _is_writable_dir(path: Path | None) -> bool:
    return bool(path and path.is_dir() and os.access(path, os.W_OK | os.X_OK))


def check_cache(config: NudebombSettings) -> CheckResult:
    """
    Check that the lookup cache directory is, or can be, writable.

    Never builds a LookupCache: its constructor creates the directory.
    """
    if not (config.tmdb_api_key or config.tvdb_api_key):
        return CheckResult("cache", SKIP, f"unused: {_NO_KEY}")
    cache_dir = Path(user_cache_dir(PROGRAM_NAME))
    path = str(cache_dir)
    if cache_dir.exists():
        if _is_writable_dir(cache_dir):
            detail = f"writable{_count_cache_entries(cache_dir)}"
            return CheckResult("cache", OK, detail, path=path)
        # A run creates subdirs at startup and would crash.
        return CheckResult("cache", FAIL, "not writable", path=path)
    parent = next((parent for parent in cache_dir.parents if parent.exists()), None)
    if _is_writable_dir(parent):
        return CheckResult("cache", OK, "will be created", path=path)
    return CheckResult("cache", FAIL, "cannot be created", path=path)


def _age(mtime: float) -> str:
    seconds = time.time() - mtime
    for unit, unit_seconds in _TIME_UNITS:
        if seconds >= unit_seconds:
            return f"{_plural(int(seconds // unit_seconds), unit)} ago"
    return "just now"


def _discard_reason(stamp_file: StampFileReport) -> str:
    if stamp_file.error:
        return stamp_file.error
    return f"config changed: {', '.join(stamp_file.diff_labels)}"


def _stamp_problems(report: TreestampsReport) -> list[str]:
    """List what the next run would do other than load the snapshot."""
    problems: list[str] = []
    snapshot, wal = report.snapshot, report.wal
    if snapshot.error or snapshot.would_discard:
        problems.append(f"next run discards it ({_discard_reason(snapshot)})")
    if wal.error or wal.would_discard:
        reason = _discard_reason(wal)
        problems.append(f"{_LEFTOVER_WAL}; the next run discards it ({reason})")
    elif wal.exists:
        entries = _plural(wal.entry_count, "entry", "entries")
        problems.append(f"{_LEFTOVER_WAL} ({entries}); the next run replays it")
    return problems


def _timestamps_result(report: TreestampsReport) -> CheckResult:
    # The file is always <root>/.nudebomb_treestamps.yaml, so no path.
    name = str(report.root_dir)
    if problems := _stamp_problems(report):
        return CheckResult(name, WARN, "; ".join(problems))
    snapshot = report.snapshot
    if not snapshot.exists or snapshot.mtime is None:
        return CheckResult(name, SKIP, "no timestamps recorded")
    entries = _plural(snapshot.entry_count, "entry", "entries")
    detail = f"{entries}, written {_age(snapshot.mtime)}"
    if snapshot.diff_labels:
        # Differences that don't discard: config checking is off.
        labels = ", ".join(snapshot.diff_labels)
        detail += f"; config differs ({labels}), ignored by -C"
    return CheckResult(name, OK, detail)


def check_timestamps(config: NudebombSettings) -> list[CheckResult]:
    """Report what the next run would make of each tree's stamp files."""
    results: list[CheckResult] = []
    present: list[str] = []
    for path_str in config.paths:
        if Path(path_str).exists():
            present.append(path_str)
        else:
            # Left out of the inspect config, or Treestamps.get_dir would
            # report on the nearest parent.
            results.append(CheckResult(path_str, FAIL, "does not exist"))
    if not present:
        return results
    try:
        reports = Grovestamps.inspect(
            build_grove_config(replace(config, paths=tuple(present)))
        )
    except Exception as exc:
        results.append(CheckResult("timestamps", FAIL, _describe(exc)))
        return results
    # A tree the config factory declines reports None; nudebomb has none.
    results.extend(_timestamps_result(report) for report in reports.values() if report)
    return results


# ── Environment ──


def _detail_text(
    detail: str = "", style: str = "", version: str = "", path: str = ""
) -> Text:
    """Join the non-empty parts with single spaces."""
    parts: list[Text] = []
    if version:
        parts.append(Text(version, DOCTOR_VERSION))
    if detail:
        parts.append(Text(detail, style))
    if path:
        parts.append(Text(f"[{path}]", DOCTOR_PATH))
    return Text(" ").join(parts)


def _requirement_names() -> list[str]:
    try:
        requirements = requires(PROGRAM_NAME) or []
    except PackageNotFoundError:
        return []
    return [
        match[0]
        for requirement in requirements
        if (match := _REQUIREMENT_NAME.match(requirement))
    ]


def _installed_version(name: str) -> tuple[str, str]:
    try:
        return version(name), DOCTOR_VERSION
    except PackageNotFoundError:
        return "not installed", DOCTOR_DETAIL_STYLES[WARN]


def _library_versions() -> Text:
    return Text(", ").join(
        Text.assemble(f"{name} ", _installed_version(name))
        for name in _requirement_names()
    )


def environment_lines(config_path: Path) -> list[tuple[str, Text]]:
    """Info rows that never fail."""
    config_found = "found" if config_path.is_file() else "not found"
    return [
        (PROGRAM_NAME, _detail_text(version=VERSION)),
        (
            "Python",
            _detail_text(version=platform.python_version(), path=sys.executable),
        ),
        ("platform", _detail_text(platform.platform())),
        ("config", _detail_text(config_found, path=str(config_path))),
        ("libraries", _library_versions()),
    ]


# ── Rendering ──

Section: TypeAlias = tuple[str, Sequence[CheckResult]]


def _check_grid() -> Table:
    grid = Table.grid(padding=(0, 2))
    grid.add_column(width=0)  # indent
    grid.add_column(width=4, no_wrap=True)
    # Timestamps names and bracketed paths are long unbroken words: fold
    # them rather than cut them off.
    grid.add_column(min_width=_NAME_WIDTH, overflow="fold")
    grid.add_column(overflow="fold")
    return grid


def _render_checks(title: str, results: Iterable[CheckResult], out: Console) -> None:
    grid = _check_grid()
    for result in results:
        mark = DOCTOR_STATUS_MARKS[result.status]
        detail = _detail_text(
            result.detail,
            DOCTOR_DETAIL_STYLES[result.status],
            result.version,
            result.path,
        )
        grid.add_row(
            "", Text(mark.char, mark.style), Text(result.name, DOCTOR_NAME), detail
        )
        if result.hint:
            hint = Text.assemble(
                ("install: ", DOCTOR_HINT), (result.hint, DOCTOR_COMMAND)
            )
            grid.add_row("", "", "", hint)
    out.print(Text(title, DOCTOR_SECTION))
    out.print(grid)
    out.print()


def _render_environment(lines: Iterable[tuple[str, Text]], out: Console) -> None:
    grid = Table.grid(padding=(0, 2))
    grid.add_column(width=0)  # indent
    grid.add_column(min_width=_LABEL_WIDTH, no_wrap=True)
    grid.add_column(overflow="fold")
    for label, value in lines:
        grid.add_row("", Text(label, DOCTOR_LABEL), value)
    out.print(Text("Environment", DOCTOR_SECTION))
    out.print(grid)
    out.print()


def _render_summary(counts: Counter[DoctorStatus], out: Console) -> None:
    def style(status: DoctorStatus) -> str:
        # Warnings and failures read as good news when there are none.
        if status in _PROBLEMS and not counts[status]:
            status = OK
        return DOCTOR_STATUS_MARKS[status].style

    out.print(
        Text.assemble(
            ("Summary: ", DOCTOR_SUMMARY),
            (f"{counts[OK]} ok", style(OK)),
            ", ",
            (_plural(counts[WARN], "warning"), style(WARN)),
            ", ",
            (f"{counts[FAIL]} failed", style(FAIL)),
            ", ",
            (f"{counts[SKIP]} skipped", style(SKIP)),
            ".",
        )
    )


def _problem_sections(sections: Iterable[Section]) -> list[Section]:
    return [
        (title, [result for result in results if result.status in _PROBLEMS])
        for title, results in sections
    ]


def render(
    sections: Sequence[Section],
    environment: Sequence[tuple[str, Text]],
    out: Console,
    *,
    problems_only: bool = False,
) -> None:
    """
    Print the report.

    With ``problems_only``, print only WARN and FAIL rows and the summary, and
    nothing at all when there are no problems.
    """
    counts = Counter(result.status for _, results in sections for result in results)
    if problems_only:
        if not counts.keys() & _PROBLEMS:
            return
        sections = _problem_sections(sections)
    for title, results in sections:
        if results:
            _render_checks(title, results, out)
    if environment:
        _render_environment(environment, out)
    _render_summary(counts, out)


# ── Doctor ──

_WRITE_FLAGS: Final = (
    ("write_config", "-w/--write-config"),
    ("write_dir_config", "-W/--write-dir-config"),
    ("write_config_file", "--write-config-file"),
)


class NudebombDoctor:
    """Check nudebomb's external dependencies against a run's config."""

    def __init__(self, arguments: Namespace) -> None:
        """Hold the arguments parsed by the doctor parser."""
        self._arguments: Namespace = arguments

    def _warn_ignored_flags(self) -> None:
        nns = self._arguments.nudebomb
        for dest, flag in _WRITE_FLAGS:
            if getattr(nns, dest):
                logger.warning(f"Ignoring {flag}: the doctor writes no files.")

    def _config_path(self) -> Path:
        """Return the -c input config path, or else the user config path."""
        if cli_config := self._arguments.nudebomb.config:
            return Path(cli_config)
        return Path(Configuration(PROGRAM_NAME, read=False).user_config_path())

    @staticmethod
    def _sections(config: NudebombSettings) -> list[Section]:
        sections: list[Section] = [
            ("Tools", (check_mkvmerge(config.mkvmerge_bin),)),
            (
                "Online lookup",
                (
                    check_tmdb(config.tmdb_api_key),
                    check_tvdb(config.tvdb_api_key, config.media_type),
                    check_cache(config),
                ),
            ),
        ]
        if config.paths:
            sections.append(("Timestamps", check_timestamps(config)))
        return sections

    def checkup(self) -> int:
        """Run the checks and print the report. Returns a process exit code."""
        config = NudebombConfig().get_doctor_config(self._arguments)
        setup_logging(config.verbose)
        self._warn_ignored_flags()
        sections = self._sections(config)
        problems_only = config.verbose <= 0
        environment = () if problems_only else environment_lines(self._config_path())
        render(sections, environment, console, problems_only=problems_only)
        failed = any(
            result.status == FAIL for _, results in sections for result in results
        )
        return int(failed)

    def doctor_mode(self) -> Never:
        """Perform a checkup and exit with its code."""
        sys.exit(self.checkup())
