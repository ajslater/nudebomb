"""Confuse config for comicbox."""

import os
import sys
from argparse import Namespace
from platform import system
from time import mktime

from confuse import Configuration
from confuse.templates import AttrDict, MappingTemplate, Optional, Sequence
from dateutil.parser import parse
from termcolor import cprint

from nudebomb.version import PROGRAM_NAME

TEMPLATE = MappingTemplate(
    {
        PROGRAM_NAME: MappingTemplate(
            {
                "after": Optional(str),
                "dry_run": bool,
                "ignore": Sequence(str),
                "languages": Sequence(str),
                "mkvmerge_bin": Optional(str),
                "paths": Sequence(str),
                "recurse": bool,
                "strip_und_language": bool,
                "sub_languages": Optional(Sequence(str)),
                "subtitles": bool,
                "symlinks": bool,
                "timestamps": bool,
                "timestamps_check_config": bool,
                "title": bool,
                "verbose": bool,
            }
        )
    }
)
TIMESTAMPS_CONFIG_KEYS = {
    "languages",
    "mkvmerge_bin",
    "recurse",
    "strip_und_language",
    "sub_languages",
    "subtitles",
    "symlinks",
    "title",
}

if system() == "Windows":
    os.system("color")  # noqa S605, S607


def _set_after(config) -> None:
    after = config[PROGRAM_NAME]["after"].get()
    if after is None:
        return

    try:
        timestamp = float(after)
    except ValueError:
        after_dt = parse(after)
        timestamp = mktime(after_dt.timetuple())

    config[PROGRAM_NAME]["after"].set(timestamp)


def _set_default_mkvmerge_bin(config):
    if config[PROGRAM_NAME]["mkvmerge_bin"].get():
        return

    if system() == "Windows":
        config[PROGRAM_NAME]["mkvmerge_bin"].set(
            "C:\\\\Program Files\\MKVToolNix\\mkvmerge.exe"
        )
    else:
        config[PROGRAM_NAME]["mkvmerge_bin"].set("mkvmerge")


def _set_unique_lang_list(config, key):
    if config[PROGRAM_NAME][key].get() is not None:
        items = set(config[PROGRAM_NAME][key].get())
        if not config[PROGRAM_NAME]["strip_und_language"].get():
            items.add("und")
        config[PROGRAM_NAME][key].set(sorted(frozenset(items)))


def _set_languages(config):
    _set_unique_lang_list(config, "languages")
    if not config[PROGRAM_NAME]["languages"].get():
        cprint(
            "Nudebomb will not run unless you set languages to keep on the "
            "command line, environment variables or config files.",
            "red",
        )
        sys.exit(1)


def _set_ignore(config) -> None:
    """Remove duplicates from the ignore list."""
    ignore: list[str] = config[PROGRAM_NAME]["ignore"].get(list)
    config[PROGRAM_NAME]["ignore"].set(tuple(sorted(set(ignore))))


def _set_timestamps(config) -> None:
    """Set the timestamp attribute."""
    timestamps = config[PROGRAM_NAME]["timestamps"].get(bool) and not config[
        PROGRAM_NAME
    ]["dry_run"].get(bool)
    config[PROGRAM_NAME]["timestamps"].set(timestamps)


def get_config(args: Namespace | None = None, modname=PROGRAM_NAME) -> AttrDict:
    """Get the config dict, layering env and args over defaults."""
    config = Configuration(PROGRAM_NAME, modname=modname, read=False)
    try:
        config.read()
    except Exception as exc:
        cprint(f"WARNING: {exc}")
    if args and args.nudebomb and args.nudebomb.config:
        config.set_file(args.nudebomb.config)
    config.set_env()
    if args:
        config.set_args(args)
    _set_languages(config)
    _set_after(config)
    _set_default_mkvmerge_bin(config)
    _set_unique_lang_list(config, "sub_languages")
    _set_ignore(config)
    _set_timestamps(config)
    ad = config.get(TEMPLATE)
    if not isinstance(ad, AttrDict):
        raise TypeError
    ad.paths = sorted(frozenset(ad.nudebomb.paths))
    return ad.nudebomb
