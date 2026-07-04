"""Confuse config for nudebomb."""

from __future__ import annotations

import sys
from contextlib import suppress
from dataclasses import dataclass
from datetime import date, datetime, time
from os import environ
from pathlib import Path, PurePath
from platform import system
from typing import TYPE_CHECKING, Final, TypedDict, cast

from confuse import Configuration
from confuse.exceptions import ConfigError
from confuse.templates import Integer, MappingTemplate, Optional, Sequence
from dateutil.parser import ParserError, parse
from loguru import logger
from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError

from nudebomb.lang import lang_to_alpha3
from nudebomb.log import console
from nudebomb.version import PROGRAM_NAME

if TYPE_CHECKING:
    from argparse import Namespace

TEMPLATE: Final = MappingTemplate(
    {
        PROGRAM_NAME: MappingTemplate(
            {
                # ``_set_after`` normalizes any input form to an epoch float
                # before template validation runs.
                "after": Optional(float),
                "cache_expiry_days": Integer(),
                "dry_run": bool,
                "ignore": Sequence(str),
                "languages": Sequence(str),
                "lookup_workers": Integer(),
                "media_type": Optional(str),
                "mkvmerge_bin": Optional(str),
                "paths": Sequence(str),
                "recurse": bool,
                "strip_und_language": bool,
                "tmdb_api_key": Optional(str),
                "tvdb_api_key": Optional(str),
                "und_language": Optional(str),
                "sub_languages": Optional(Sequence(str)),
                "subtitles": bool,
                "symlinks": bool,
                "timestamps": bool,
                "timestamps_check_config": bool,
                "title": bool,
                "verbose": Integer(),
            }
        )
    }
)
TIMESTAMPS_CONFIG_KEYS: Final = frozenset(
    {
        "languages",
        "mkvmerge_bin",
        "recurse",
        "strip_und_language",
        "und_language",
        "sub_languages",
        "subtitles",
        "symlinks",
        "title",
    }
)

# Per-directory config files layer beneath env vars and CLI args but above
# the user config. Named to match the timestamps file ``.nudebomb_treestamps.yaml``
# without colliding with it. See :class:`nudebomb.config.dirconfig.DirConfig`.
DIR_CONFIG_FILENAME: Final = ".nudebomb.yaml"

# CLI args the config writers never persist: the write flags and -c INPUT
# path themselves, paths (argparse requires them on every invocation
# anyway), and the ephemeral run-mode flags dry_run / verbose — persisting
# those turns a one-off preview or -q into a permanent default (a sticky
# dry_run would make every future run a silent no-op). Users who truly want
# them as defaults can hand-edit the file; they are still honored on read.
_UNPERSISTED_ARGS: Final = frozenset(
    {
        "config",
        "paths",
        "write_config",
        "write_dir_config",
        "write_config_file",
        "dry_run",
        "verbose",
    }
)

if system() == "Windows":
    from colorama import just_fix_windows_console

    just_fix_windows_console()


@dataclass(slots=True)
class NudebombSettings:
    """
    Typed runtime config for nudebomb.

    Built once by :meth:`NudebombConfig.get_config` from a confuse-validated
    ``AttrDict``; every downstream module takes ``NudebombSettings`` so
    consumers never have to touch the loosely-typed AttrDict.

    Not ``frozen``: ``Walk.strip_path`` deepcopies the run-wide settings
    and overrides ``languages`` per-file from a discovered langfile, and
    ``MKVFile.update_languages`` augments it again after a DB lookup
    resolves. Both paths mutate the per-file copy, never the run-wide
    instance.
    """

    # Sequence-shaped fields. ``languages`` and ``sub_languages`` use
    # ``frozenset`` because consumers do set-algebra on them
    # (``config.languages | {lang}``); ``paths`` and ``ignore`` keep
    # iteration order so ``tuple`` is right.
    paths: tuple[str, ...]
    languages: frozenset[str]
    sub_languages: frozenset[str] | None
    ignore: tuple[str, ...]

    # Numeric fields
    after: float | None
    cache_expiry_days: int
    lookup_workers: int
    verbose: int

    # String fields
    media_type: str | None
    mkvmerge_bin: str
    tmdb_api_key: str | None
    tvdb_api_key: str | None
    und_language: str | None

    # Boolean fields
    dry_run: bool
    recurse: bool
    strip_und_language: bool
    subtitles: bool
    symlinks: bool
    timestamps: bool
    timestamps_check_config: bool
    title: bool


class _NudebombSchema(TypedDict):
    """
    Static-typing view of the nudebomb section of the validated AttrDict.

    confuse 2.2.0 returns ``AttrDict[str, object]`` from ``MappingTemplate``;
    the runtime types are guaranteed by ``TEMPLATE`` validation. This
    TypedDict declares those types so the conversion in
    :meth:`NudebombConfig.get_config` type-checks via a single ``cast``
    rather than a per-field cast.
    """

    after: float | None
    cache_expiry_days: int
    dry_run: bool
    ignore: list[str]
    languages: list[str]
    lookup_workers: int
    media_type: str | None
    mkvmerge_bin: str
    paths: list[str]
    recurse: bool
    strip_und_language: bool
    sub_languages: list[str] | None
    subtitles: bool
    symlinks: bool
    timestamps: bool
    timestamps_check_config: bool
    title: bool
    tmdb_api_key: str | None
    tvdb_api_key: str | None
    und_language: str | None
    verbose: int


def _invoked_cli_options(nns: Namespace) -> dict:
    """Return the options explicitly given on the command line."""
    # Unset options are None (argparse flag defaults are None so config
    # layering works), so non-None values are exactly what was invoked.
    return {
        key: value
        for key, value in vars(nns).items()
        if value is not None and key not in _UNPERSISTED_ARGS
    }


def merge_config_file(target: Path, base_path: Path, options: dict) -> None:
    """
    Merge ``options`` into ``base_path``'s config section and write to ``target``.

    Round-trip loads ``base_path`` so existing keys and comments survive, then
    writes owner-only (the config can hold API keys). Raises ``YAMLError`` or
    ``OSError`` on read/write failure so callers decide whether it is fatal.
    """
    yaml = YAML()
    data = yaml.load(base_path.read_text()) if base_path.is_file() else None
    if not isinstance(data, dict):
        data = {}
    section = data.get(PROGRAM_NAME)
    if not isinstance(section, dict):
        section = {}
        data[PROGRAM_NAME] = section
    section.update(options)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w") as stream:
        yaml.dump(data, stream)
    # Best effort: filesystems without POSIX modes (e.g. FAT) just skip it.
    with suppress(OSError):
        target.chmod(0o600)


def _write_merged_config(
    target: Path, base_path: Path, options: dict, verbose: int
) -> None:
    """Write a config for the -w/-W/--write-config-file flags; fatal on failure."""
    try:
        merge_config_file(target, base_path, options)
    except (YAMLError, OSError) as exc:
        logger.error(f"Could not write config file {target}: {exc}")
        sys.exit(1)
    # Confirm this explicitly-requested action at default verbosity, but
    # honor -q (verbose 0) like every other user-facing message.
    if verbose > 0:
        console.print(
            f"Wrote config to {target}", markup=False, highlight=False, soft_wrap=True
        )


def _target_dir_config_paths(paths: list[str]) -> list[Path]:
    """Deduped, order-stable ``.nudebomb.yaml`` path for each target directory."""
    targets: dict[Path, None] = {}
    for path_str in paths:
        path = Path(path_str)
        # A file target's config lives in its parent directory (matches
        # Walk._config_candidates).
        directory = path if path.is_dir() else path.parent
        targets[directory / DIR_CONFIG_FILENAME] = None
    return list(targets)


def _write_configs(config: Configuration, nns: Namespace) -> None:
    """Persist the invoked options per the write flags."""
    options = _invoked_cli_options(nns)
    verbose = config[PROGRAM_NAME]["verbose"].get(int)
    # ``-c`` INPUT is the merge base for the user/explicit-path writes.
    base = Path(nns.config) if nns.config else None
    if nns.write_config:
        target = Path(config.user_config_path())
        _write_merged_config(target, base or target, options, verbose)
    if nns.write_config_file:
        target = Path(nns.write_config_file)
        _write_merged_config(target, base or target, options, verbose)
    if nns.write_dir_config:
        # Each directory config is updated in place; -c is not a base here.
        for target in _target_dir_config_paths(nns.paths):
            _write_merged_config(target, target, options, verbose)


class NudebombConfig:
    """Nudebomb config."""

    @staticmethod
    def _parse_after(after: object) -> float:
        """Convert an epoch number, datetime string, or YAML date to an epoch float."""
        # Unquoted dates in YAML config files arrive as date/datetime objects.
        if isinstance(after, datetime):
            return after.timestamp()
        if isinstance(after, date):
            return datetime.combine(after, time.min).timestamp()
        if isinstance(after, int | float):
            return float(after)
        after_str = str(after)
        try:
            return float(after_str)
        except ValueError:
            # ``timestamp()`` honors an explicit timezone offset and reads
            # naive datetimes as local time.
            return parse(after_str).timestamp()

    @classmethod
    def _set_after(cls, config: Configuration) -> None:
        after = config[PROGRAM_NAME]["after"].get()
        if after is None:
            return

        try:
            timestamp = cls._parse_after(after)
        except (ParserError, OverflowError, ValueError) as exc:
            logger.error(f"Invalid after value {after!r}: {exc}")
            sys.exit(1)

        config[PROGRAM_NAME]["after"].set(timestamp)

    @staticmethod
    def _set_default_mkvmerge_bin(config: Configuration) -> None:
        if config[PROGRAM_NAME]["mkvmerge_bin"].get():
            return

        if system() == "Windows":
            # Honor a relocated Program Files (non-standard install
            # drives). NOTE: mkvmerge_bin participates in the timestamp
            # config check, so correcting the old doubled-backslash
            # literal invalidates existing -t records once.
            program_files = environ.get("PROGRAMFILES", "C:\\Program Files")
            config[PROGRAM_NAME]["mkvmerge_bin"].set(
                str(PurePath(program_files) / "MKVToolNix" / "mkvmerge.exe")
            )
        else:
            config[PROGRAM_NAME]["mkvmerge_bin"].set("mkvmerge")

    @staticmethod
    def _set_unique_lang_list(config: Configuration, key: str) -> None:
        value = config[PROGRAM_NAME][key].get()
        if value is None:
            return
        if not isinstance(value, list | tuple):
            # A scalar (e.g. ``languages: eng`` in a config file or
            # ``NUDEBOMB_NUDEBOMB__LANGUAGES=eng``) would otherwise be
            # iterated character by character.
            logger.error(
                f"{key} must be a list of language codes, got {value!r}. "
                f"Use a comma separated option like '-l eng,fra', a YAML "
                f"list, or enumerated environment variables like "
                f"NUDEBOMB_NUDEBOMB__{key.upper()}__0=eng."
            )
            sys.exit(1)
        items = {
            lang_to_alpha3(stripped)
            for item in value
            if (stripped := str(item).strip())
        }
        und_language = config[PROGRAM_NAME]["und_language"].get()
        strip_und = config[PROGRAM_NAME]["strip_und_language"].get()
        if und_language or not strip_und:
            items.add("und")
        config[PROGRAM_NAME][key].set(sorted(items))

    @staticmethod
    def _set_und_language(config: Configuration) -> None:
        """Normalize und_language to ISO 639-3 (alpha3) format."""
        und_language = config[PROGRAM_NAME]["und_language"].get()
        if und_language:
            config[PROGRAM_NAME]["und_language"].set(lang_to_alpha3(und_language))

    def _set_languages(self, config: Configuration) -> None:
        self._set_unique_lang_list(config, "languages")
        if not config[PROGRAM_NAME]["languages"].get():
            error = "Nudebomb will not run unless you set languages to keep on the command line, environment variables or config files."
            logger.error(error)
            sys.exit(1)

    @staticmethod
    def _set_ignore(config: Configuration) -> None:
        """Remove duplicates from the ignore list."""
        ignore: list[str] = config[PROGRAM_NAME]["ignore"].get(list)
        config[PROGRAM_NAME]["ignore"].set(tuple(sorted(set(ignore))))

    @staticmethod
    def _read_sources(config: Configuration, nns: Namespace | None) -> None:
        """
        Load config file sources beneath env vars and CLI args.

        With -c, that file is the input config and fully replaces the
        user's default config; only the packaged defaults remain beneath
        it. Without -c, the user's default config is read as usual.
        """
        cli_config = nns.config if nns else None
        if cli_config:
            config.read(user=False)
            try:
                config.set_file(cli_config)
            except ConfigError as exc:
                logger.error(f"Could not read config file {cli_config}: {exc}")
                sys.exit(1)
            return
        try:
            config.read()
        except Exception as exc:
            # A broken user config must not also drop the packaged
            # defaults, or the first template access crashes with an
            # unrelated NotFoundError.
            logger.error(f"Could not read the user config file: {exc}")
            config.read(user=False)

    @staticmethod
    def _to_settings(nb_attrdict: object) -> NudebombSettings:
        """
        Convert the validated nudebomb AttrDict into a typed Settings.

        Accepts ``object`` because confuse 2.2.0's typing for the inner
        AttrDict (``AttrDict[str, int | str | list[str] | None]``) and our
        ``_NudebombSchema`` TypedDict don't formally overlap; the cast
        through ``object`` is the documented escape hatch for crossing
        between confuse's runtime-validated dict and a TypedDict view.
        """
        nb = cast("_NudebombSchema", nb_attrdict)
        sub_langs = nb["sub_languages"]
        return NudebombSettings(
            paths=tuple(nb["paths"]),
            languages=frozenset(nb["languages"]),
            sub_languages=frozenset(sub_langs) if sub_langs else None,
            ignore=tuple(nb["ignore"]),
            after=nb["after"],
            cache_expiry_days=nb["cache_expiry_days"],
            lookup_workers=nb["lookup_workers"],
            verbose=nb["verbose"],
            media_type=nb["media_type"],
            mkvmerge_bin=nb["mkvmerge_bin"],
            tmdb_api_key=nb["tmdb_api_key"],
            tvdb_api_key=nb["tvdb_api_key"],
            und_language=nb["und_language"],
            dry_run=nb["dry_run"],
            recurse=nb["recurse"],
            strip_und_language=nb["strip_und_language"],
            subtitles=nb["subtitles"],
            symlinks=nb["symlinks"],
            timestamps=nb["timestamps"],
            timestamps_check_config=nb["timestamps_check_config"],
            title=nb["title"],
        )

    def _build_config(
        self,
        args: Namespace | None = None,
        dir_config_files: tuple[Path, ...] = (),
        modname: str = PROGRAM_NAME,
    ) -> Configuration:
        """
        Build a fully-layered, normalized confuse Configuration.

        Sources, lowest→highest priority: packaged defaults, user config
        (or the ``-c`` replacement), each directory ``.nudebomb.yaml``
        (shallowest→deepest), env vars, CLI args. Each ``set_*`` call
        appends to the confuse source stack, so the directory files sit
        above the user config yet below env/args — deeper directories win
        over shallower ones, and env/CLI still win over every directory
        file. Shared by :meth:`get_config` (no directory files) and
        :class:`nudebomb.config.dirconfig.DirConfig` (per-directory chain).
        """
        config = Configuration(PROGRAM_NAME, modname=modname, read=False)
        nns = args.nudebomb if args else None
        self._read_sources(config, nns)
        for dir_config_file in dir_config_files:
            config.set_file(str(dir_config_file))
        config.set_env()
        if args:
            config.set_args(args)
        self._set_und_language(config)
        self._set_languages(config)
        self._set_after(config)
        self._set_default_mkvmerge_bin(config)
        self._set_unique_lang_list(config, "sub_languages")
        self._set_ignore(config)
        return config

    def _config_to_settings(self, config: Configuration) -> NudebombSettings:
        """Validate against the template and convert to typed settings."""
        # confuse 2.2.0 types the result of ``config.get(TEMPLATE)``
        # precisely from the MappingTemplate, so an ``isinstance``
        # narrowing is no longer needed.
        ad = config.get(TEMPLATE)
        return self._to_settings(ad.nudebomb)

    def get_config(
        self,
        args: Namespace | None = None,
        modname: str = PROGRAM_NAME,
    ) -> NudebombSettings:
        """Get the typed config, layering env and args over defaults."""
        config = self._build_config(args, modname=modname)
        nns = args.nudebomb if args else None
        # Validate (via ``_config_to_settings``) before persisting so a bad
        # command line can't poison the config file.
        settings = self._config_to_settings(config)
        if nns is not None and (
            nns.write_config or nns.write_dir_config or nns.write_config_file
        ):
            _write_configs(config, nns)
        return settings

    def get_dir_settings(
        self,
        args: Namespace | None,
        dir_config_files: tuple[Path, ...],
    ) -> NudebombSettings:
        """
        Resolve settings with per-directory config files layered in.

        Like :meth:`get_config` but for the per-directory chain: the
        directory ``.nudebomb.yaml`` files layer beneath env/CLI and above
        the user config, and ``-w`` is never triggered. Used by
        :class:`nudebomb.config.dirconfig.DirConfig`.
        """
        config = self._build_config(args, dir_config_files)
        return self._config_to_settings(config)
