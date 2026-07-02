"""Tests for config layering, normalization, and error handling."""

from datetime import date, datetime, time, timezone

import pytest
from dateutil.parser import parse

from nudebomb.cli import get_arguments
from nudebomb.config import NudebombConfig, NudebombSettings

__all__ = ()

BASE_ARGV = ("nudebomb", "-l", "eng", "/tmp")  # noqa: S108
EPOCH = 1700000000.0
VERBOSE_TWO = 2


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
