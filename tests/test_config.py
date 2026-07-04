"""Tests for config layering, normalization, and error handling."""

from datetime import date, datetime, time, timezone
from pathlib import Path

import pytest
from dateutil.parser import parse
from ruamel.yaml import YAML

from nudebomb.cli import get_arguments
from nudebomb.config import NudebombConfig, NudebombSettings


def yaml_load(path: Path) -> dict:
    """Load a YAML file for assertions."""
    return YAML().load(path.read_text())


__all__ = ()

BASE_ARGV = ("nudebomb", "-l", "eng", "/tmp")  # noqa: S108
EPOCH = 1700000000.0
VERBOSE_TWO = 2
OWNER_ONLY_MODE = 0o600


@pytest.fixture(autouse=True)
def _isolate_config(monkeypatch, tmp_path):
    """Point confuse at an empty config dir and scrub nudebomb env vars."""
    import os

    for key in list(os.environ):
        if key.startswith("NUDEBOMB"):
            monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("NUDEBOMBDIR", str(tmp_path))


def _get_config(argv: tuple[str, ...] = BASE_ARGV) -> NudebombSettings:
    return NudebombConfig().get_config(get_arguments(argv))


def _write_config(tmp_path, yaml_text: str) -> None:
    (tmp_path / "config.yaml").write_text(yaml_text)


class TestAfter:
    """--after parses every documented input form and fails cleanly."""

    def test_epoch_number(self):
        config = _get_config((*BASE_ARGV[:-1], "-A", str(int(EPOCH)), "/tmp"))  # noqa: S108
        assert config.after == EPOCH

    def test_datetime_string(self):
        config = _get_config((*BASE_ARGV[:-1], "-A", "2020-01-02T03:04:05", "/tmp"))  # noqa: S108
        assert config.after == parse("2020-01-02T03:04:05").timestamp()

    def test_timezone_aware_string(self):
        config = _get_config(
            (*BASE_ARGV[:-1], "-A", "2026-01-01T12:00:00+00:00", "/tmp")  # noqa: S108
        )
        expected = datetime(2026, 1, 1, 12, tzinfo=timezone.utc).timestamp()
        assert config.after == expected

    def test_yaml_date_object(self, tmp_path):
        _write_config(tmp_path, "nudebomb:\n  after: 2020-01-01\n")
        config = _get_config()
        expected = datetime.combine(date(2020, 1, 1), time.min).timestamp()
        assert config.after == expected

    def test_garbage_exits_cleanly(self):
        with pytest.raises(SystemExit):
            _get_config((*BASE_ARGV[:-1], "-A", "not-a-date", "/tmp"))  # noqa: S108


class TestLanguageLists:
    """Language lists are split, stripped, normalized, and validated."""

    def test_comma_list_strips_items(self):
        args = get_arguments(("nudebomb", "-l", "eng, fra", "/tmp"))  # noqa: S108
        assert args.nudebomb.languages == ["eng", "fra"]

    def test_comma_list_drops_empty_items(self):
        args = get_arguments(("nudebomb", "-l", "eng,,fra,", "/tmp"))  # noqa: S108
        assert args.nudebomb.languages == ["eng", "fra"]

    def test_languages_normalized_to_alpha3(self):
        config = _get_config(("nudebomb", "-l", "en, fr", "/tmp"))  # noqa: S108
        assert config.languages == frozenset({"eng", "fra", "und"})

    def test_sub_languages_normalized_to_alpha3(self):
        config = _get_config(("nudebomb", "-l", "eng", "-s", "en", "/tmp"))  # noqa: S108
        assert config.sub_languages == frozenset({"eng", "und"})

    def test_scalar_env_languages_rejected(self, monkeypatch):
        monkeypatch.setenv("NUDEBOMB_NUDEBOMB__LANGUAGES", "eng")
        with pytest.raises(SystemExit):
            _get_config(("nudebomb", "/tmp"))  # noqa: S108

    def test_scalar_config_languages_rejected(self, tmp_path):
        _write_config(tmp_path, "nudebomb:\n  languages: eng\n")
        with pytest.raises(SystemExit):
            _get_config(("nudebomb", "/tmp"))  # noqa: S108


class TestLayering:
    """Env vars and config files are honored unless the CLI overrides them."""

    def test_config_file_flags_apply(self, tmp_path):
        _write_config(
            tmp_path,
            "nudebomb:\n"
            "  dry_run: true\n"
            "  recurse: true\n"
            "  media_type: movie\n"
            "  verbose: 2\n"
            "  subtitles: false\n",
        )
        config = _get_config()
        assert config.dry_run is True
        assert config.recurse is True
        assert config.media_type == "movie"
        assert config.verbose == VERBOSE_TWO
        assert config.subtitles is False

    def test_env_var_flag_applies(self, monkeypatch):
        monkeypatch.setenv("NUDEBOMB_NUDEBOMB__RECURSE", "True")
        config = _get_config()
        assert config.recurse is True

    def test_cli_overrides_config_file(self, tmp_path):
        _write_config(tmp_path, "nudebomb:\n  dry_run: false\n")
        config = _get_config((*BASE_ARGV[:-1], "-d", "/tmp"))  # noqa: S108
        assert config.dry_run is True

    def test_c_input_replaces_user_config(self, tmp_path):
        """-c is the config for the run; the user's default config is ignored."""
        _write_config(tmp_path, "nudebomb:\n  recurse: true\n  languages: [deu]\n")
        inp = tmp_path / "in.yaml"
        inp.write_text("nudebomb:\n  languages: [jpn]\n")
        config = _get_config(("nudebomb", "-c", str(inp), "/tmp"))  # noqa: S108
        assert config.recurse is False  # user config's recurse not layered in
        assert config.languages == frozenset({"jpn", "und"})  # from -c, not deu

    def test_dry_run_keeps_timestamp_reads(self):
        """-d -t keeps timestamps on so the preview matches a real run."""
        config = _get_config((*BASE_ARGV[:-1], "-d", "-t", "/tmp"))  # noqa: S108
        assert config.dry_run is True
        assert config.timestamps is True

    def test_defaults_without_flags(self):
        config = _get_config()
        assert config.dry_run is False
        assert config.recurse is False
        assert config.subtitles is True
        assert config.verbose == 1
        assert config.media_type is None


class TestConfigErrors:
    """Config problems produce clean errors, not tracebacks."""

    def test_malformed_config_falls_back_to_defaults(self, tmp_path):
        _write_config(tmp_path, "nudebomb:\n  bad: [unclosed\n")
        config = _get_config()
        assert config.dry_run is False

    def test_missing_dash_c_file_exits_cleanly(self):
        with pytest.raises(SystemExit):
            _get_config((*BASE_ARGV[:-1], "-c", "/nonexistent/nope.yaml", "/tmp"))  # noqa: S108

    def test_invalid_media_type_rejected(self):
        with pytest.raises(SystemExit):
            _get_config((*BASE_ARGV[:-1], "-m", "film", "/tmp"))  # noqa: S108


class TestWriteConfig:
    """-w writes the user config; --write-config-file writes an explicit path."""

    def test_w_writes_user_config(self, tmp_path):
        """Bare -w writes invoked options to the auto-located user config."""
        _get_config(("nudebomb", "-w", "-l", "eng,fra", "-r", "/tmp"))  # noqa: S108
        section = yaml_load(tmp_path / "config.yaml")["nudebomb"]
        assert section["languages"] == ["eng", "fra"]
        assert section["recurse"] is True
        assert "paths" not in section
        assert "write_config" not in section
        assert "config" not in section
        assert "dry_run" not in section

    def test_run_mode_flags_not_persisted(self, tmp_path):
        """-d and -q/-v are ephemeral run modes, never written as defaults."""
        _get_config(("nudebomb", "-w", "-d", "-q", "-l", "eng", "/tmp"))  # noqa: S108
        section = yaml_load(tmp_path / "config.yaml")["nudebomb"]
        assert "dry_run" not in section
        assert "verbose" not in section
        assert section["languages"] == ["eng"]

    def test_w_merges_c_input_leaving_input_untouched(self, tmp_path):
        inp = tmp_path / "in.yaml"
        inp.write_text("nudebomb:\n  tmdb_api_key: abc123\n  languages: [jpn]\n")
        _get_config(("nudebomb", "-c", str(inp), "-w", "-l", "eng", "/tmp"))  # noqa: S108
        section = yaml_load(tmp_path / "config.yaml")["nudebomb"]
        assert section["tmdb_api_key"] == "abc123"  # carried from -c input
        assert section["languages"] == ["eng"]  # CLI overrides the input
        assert yaml_load(inp)["nudebomb"]["languages"] == ["jpn"]  # input untouched

    def test_w_in_place_preserves_comments(self, tmp_path):
        cfg = tmp_path / "config.yaml"  # the user config, pre-existing
        cfg.write_text(
            "nudebomb:\n  # keep this comment\n  tmdb_api_key: abc\n  languages: [fra]\n"
        )
        _get_config(("nudebomb", "-w", "-l", "eng", "/tmp"))  # noqa: S108
        text = cfg.read_text()
        assert "# keep this comment" in text
        section = yaml_load(cfg)["nudebomb"]
        assert section["tmdb_api_key"] == "abc"
        assert section["languages"] == ["eng"]

    def test_written_file_is_owner_only(self, tmp_path):
        _get_config(("nudebomb", "-w", "-l", "eng", "/tmp"))  # noqa: S108
        assert ((tmp_path / "config.yaml").stat().st_mode & 0o777) == OWNER_ONLY_MODE

    def test_quiet_suppresses_confirmation(self, tmp_path, capsys):
        _get_config(("nudebomb", "-w", "-q", "-l", "eng", "/tmp"))  # noqa: S108
        assert "Wrote config" not in capsys.readouterr().out
        assert (tmp_path / "config.yaml").is_file()

    def test_written_config_round_trips_via_c(self, tmp_path):
        _get_config(("nudebomb", "-w", "-l", "eng,fra", "-r", "/tmp"))  # noqa: S108
        config = _get_config(("nudebomb", "-c", str(tmp_path / "config.yaml"), "/tmp"))  # noqa: S108
        assert config.recurse is True
        assert {"eng", "fra"} <= config.languages

    def test_invalid_invocation_does_not_write(self, tmp_path, monkeypatch):
        monkeypatch.setenv("NUDEBOMB_NUDEBOMB__LANGUAGES", "eng")  # scalar -> rejected
        with pytest.raises(SystemExit):
            _get_config(("nudebomb", "-w", "/tmp"))  # noqa: S108
        assert not (tmp_path / "config.yaml").exists()

    def test_no_write_without_flag(self, tmp_path):
        _get_config(BASE_ARGV)
        assert not (tmp_path / "config.yaml").exists()

    def test_write_config_file_explicit_path(self, tmp_path):
        out = tmp_path / "sub" / "custom.yaml"
        _get_config(
            (
                "nudebomb",
                "--write-config-file",
                str(out),
                "-l",
                "eng,fra",
                "-r",
                str(tmp_path),
            )
        )
        section = yaml_load(out)["nudebomb"]
        assert section["languages"] == ["eng", "fra"]
        assert section["recurse"] is True
        assert (out.stat().st_mode & 0o777) == OWNER_ONLY_MODE

    def test_write_config_file_merges_c_input(self, tmp_path):
        inp = tmp_path / "in.yaml"
        inp.write_text("nudebomb:\n  tmdb_api_key: abc123\n  languages: [jpn]\n")
        out = tmp_path / "out.yaml"
        _get_config(
            (
                "nudebomb",
                "-c",
                str(inp),
                "--write-config-file",
                str(out),
                "-l",
                "eng",
                str(tmp_path),
            )
        )
        section = yaml_load(out)["nudebomb"]
        assert section["tmdb_api_key"] == "abc123"
        assert section["languages"] == ["eng"]
        assert yaml_load(inp)["nudebomb"]["languages"] == ["jpn"]  # input untouched

    def test_write_dir_config_each_target_dir(self, tmp_path):
        anime = tmp_path / "anime"
        movies = tmp_path / "movies"
        anime.mkdir()
        movies.mkdir()
        _get_config(
            ("nudebomb", "-W", "-l", "eng", "-s", "jpn", str(anime), str(movies))
        )
        for directory in (anime, movies):
            section = yaml_load(directory / ".nudebomb.yaml")["nudebomb"]
            assert section["languages"] == ["eng"]
            assert section["sub_languages"] == ["jpn"]

    def test_write_dir_config_file_target_writes_parent(self, tmp_path):
        show = tmp_path / "show"
        show.mkdir()
        episode = show / "ep.mkv"
        episode.write_bytes(b"x")
        _get_config(("nudebomb", "-W", "-l", "eng", str(episode)))
        assert yaml_load(show / ".nudebomb.yaml")["nudebomb"]["languages"] == ["eng"]

    def test_write_dir_config_and_user_config_together(self, tmp_path):
        directory = tmp_path / "d"
        directory.mkdir()
        _get_config(("nudebomb", "-w", "-W", "-l", "eng", str(directory)))
        assert (tmp_path / "config.yaml").is_file()  # user config
        assert (directory / ".nudebomb.yaml").is_file()  # directory config


def test_target_dir_config_paths_dedupes_and_uses_parent(tmp_path):
    """File targets resolve to their parent dir; duplicates collapse to one."""
    from nudebomb.config import _target_dir_config_paths

    directory = tmp_path / "d"
    directory.mkdir()
    (directory / "a.mkv").write_bytes(b"x")
    (directory / "b.mkv").write_bytes(b"x")
    paths = _target_dir_config_paths(
        [str(directory / "a.mkv"), str(directory / "b.mkv"), str(directory)]
    )
    assert paths == [directory / ".nudebomb.yaml"]


class TestVerbose:
    """Verbose flag mapping: None passthrough, -v increments, -q pins 0."""

    def test_no_flag_is_none(self):
        args = get_arguments(BASE_ARGV)
        assert args.nudebomb.verbose is None

    def test_single_v_is_two(self):
        args = get_arguments((*BASE_ARGV[:-1], "-v", "/tmp"))  # noqa: S108
        assert args.nudebomb.verbose == VERBOSE_TWO

    def test_quiet_is_zero(self):
        args = get_arguments((*BASE_ARGV[:-1], "-q", "/tmp"))  # noqa: S108
        assert args.nudebomb.verbose == 0
