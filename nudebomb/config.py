"""Confuse config for nudebomb."""

import os
import sys
from argparse import Namespace
from pathlib import Path
from platform import system
from time import mktime
from typing import Final

from confuse import Configuration
from confuse.templates import AttrDict, Integer, MappingTemplate, Optional, Sequence
from dateutil.parser import parse

from nudebomb.langfiles import lang_to_alpha3
from nudebomb.printer import Printer
from nudebomb.version import PROGRAM_NAME

TEMPLATE: Final = MappingTemplate(
    {
        PROGRAM_NAME: MappingTemplate(
            {
                "after": Optional(str),
                "dry_run": bool,
                "ignore": Sequence(str),
                "languages": Sequence(str),
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


class NudebombConfig:
    """Nudebomb config."""

    def __init__(self) -> None:
        """Initialize printer."""
        self._printer: Printer = Printer(2)

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
            self._printer.error(error)
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

    def get_config(
        self,
        args: Namespace | None = None,
        modname: str = PROGRAM_NAME,
    ) -> AttrDict:
        """Get the config dict, layering env and args over defaults."""
        config = Configuration(PROGRAM_NAME, modname=modname, read=False)
        try:
            config.read()
        except Exception as exc:
            self._printer.warn(str(exc))
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
        ad = config.get(TEMPLATE)
        if not isinstance(ad, AttrDict):
            raise TypeError
        ad.paths = sorted(
            frozenset(str(Path(path).resolve()) for path in ad.nudebomb.paths)
        )
        return ad.nudebomb
