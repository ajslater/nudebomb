"""Confuse config for nudebomb."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from platform import system
from time import mktime
from typing import TYPE_CHECKING, Final, TypedDict, cast

from confuse import Configuration
from confuse.templates import Integer, MappingTemplate, Optional, Sequence
from dateutil.parser import parse
from loguru import logger

from nudebomb.lang import lang_to_alpha3
from nudebomb.version import PROGRAM_NAME

if TYPE_CHECKING:
    from argparse import Namespace

TEMPLATE: Final = MappingTemplate(
    {
        PROGRAM_NAME: MappingTemplate(
            {
                "after": Optional(str),
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

if system() == "Windows":
    os.system("color")  # noqa: S605, S607


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


class NudebombConfig:
    """Nudebomb config."""

    @staticmethod
    def _set_after(config: Configuration) -> None:
        after = config[PROGRAM_NAME]["after"].get()
        if after is None:
            return

        try:
            timestamp = float(after)
        except ValueError:
            after_dt = parse(after)
            timestamp = mktime(after_dt.timetuple())

        config[PROGRAM_NAME]["after"].set(timestamp)

    @staticmethod
    def _set_default_mkvmerge_bin(config: Configuration) -> None:
        if config[PROGRAM_NAME]["mkvmerge_bin"].get():
            return

        if system() == "Windows":
            config[PROGRAM_NAME]["mkvmerge_bin"].set(
                "C:\\\\Program Files\\MKVToolNix\\mkvmerge.exe"
            )
        else:
            config[PROGRAM_NAME]["mkvmerge_bin"].set("mkvmerge")

    @staticmethod
    def _set_unique_lang_list(config: Configuration, key: str) -> None:
        if config[PROGRAM_NAME][key].get() is not None:
            items = set(config[PROGRAM_NAME][key].get())
            und_language = config[PROGRAM_NAME]["und_language"].get()
            strip_und = config[PROGRAM_NAME]["strip_und_language"].get()
            if und_language or not strip_und:
                items.add("und")
            config[PROGRAM_NAME][key].set(sorted(frozenset(items)))

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
    def _set_timestamps(config: Configuration) -> None:
        """Set the timestamp attribute."""
        timestamps = config[PROGRAM_NAME]["timestamps"].get(bool) and not config[
            PROGRAM_NAME
        ]["dry_run"].get(bool)
        config[PROGRAM_NAME]["timestamps"].set(timestamps)

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

    def get_config(
        self,
        args: Namespace | None = None,
        modname: str = PROGRAM_NAME,
    ) -> NudebombSettings:
        """Get the typed config, layering env and args over defaults."""
        config = Configuration(PROGRAM_NAME, modname=modname, read=False)
        try:
            config.read()
        except Exception as exc:
            logger.warning(str(exc))
        if args and args.nudebomb and args.nudebomb.config:
            config.set_file(args.nudebomb.config)
        config.set_env()
        if args:
            config.set_args(args)
        self._set_und_language(config)
        self._set_languages(config)
        self._set_after(config)
        self._set_default_mkvmerge_bin(config)
        self._set_unique_lang_list(config, "sub_languages")
        self._set_ignore(config)
        self._set_timestamps(config)
        # confuse 2.2.0 types the result of ``config.get(TEMPLATE)``
        # precisely from the MappingTemplate, so an ``isinstance``
        # narrowing is no longer needed.
        ad = config.get(TEMPLATE)
        return self._to_settings(ad.nudebomb)
