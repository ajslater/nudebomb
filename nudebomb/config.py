"""Confuse config for comicbox."""
import os
import sys
import typing

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
        "nudebomb": MappingTemplate(
            {
                "after": Optional(str),
                "dry_run": bool,
                "languages": Sequence(str),
                "mkvmerge_bin": Optional(str),
                "paths": Sequence(str),
                "recurse": bool,
                "strip_und_language": bool,
                "subs_languages": Optional(Sequence(str)),
                "subtitles": bool,
                "symlinks": bool,
                "timestamps": bool,
                "title": bool,
                "verbose": bool,
            }
        )
    }
)
TIMESTAMPS_CONFIG_KEYS = set(
    (
        "languages",
        "mkvmerge_bin",
        "recurse",
        "strip_und_language",
        "subs_languages",
        "subtitles",
        "symlinks",
        "title",
    )
)

if system() == "Windows":
    os.system("color")


def _set_after(config) -> None:
    after = config["nudebomb"]["after"].get()
    if after is None:
        return

    try:
        timestamp = float(after)
    except ValueError:
        after_dt = parse(after)
        timestamp = mktime(after_dt.timetuple())

    config["nudebomb"]["after"].set(timestamp)


def _set_default_mkvmerge_bin(config):
    if config["nudebomb"]["mkvmerge_bin"].get():
        return

    if system() == "Windows":
        config["nudebomb"]["mkvmerge_bin"].set(
            "C:\\\\Program Files\\MKVToolNix\\mkvmerge.exe"
        )
    else:
        config["nudebomb"]["mkvmerge_bin"].set("mkvmerge")


def _set_unique_lang_list(config, key):
    if config["nudebomb"][key].get() is not None:
        items = set(config["nudebomb"][key].get())
        if not config["nudebomb"]["strip_und_language"].get():
            items.add("und")
        config["nudebomb"][key].set(sorted(frozenset(items)))


def _set_languages(config):
    _set_unique_lang_list(config, "languages")
    if not config["nudebomb"]["languages"].get():
        cprint(
            "Nudebomb will not run unless you set languages to keep on the "
            "command line, environment variables or config files.",
            "red",
        )
        sys.exit(1)


def _set_timestamps(config) -> None:
    """Set the timestamp attribute."""
    timestamps = config["nudebomb"]["timestamps"].get(bool) and not config["nudebomb"][
        "dry_run"
    ].get(bool)
    config["nudebomb"]["timestamps"].set(timestamps)


def get_config(
    args: typing.Optional[Namespace] = None, modname=PROGRAM_NAME
) -> AttrDict:
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
    _set_unique_lang_list(config, "subs_languages")
    _set_timestamps(config)
    ad = config.get(TEMPLATE)
    if not isinstance(ad, AttrDict):
        raise ValueError()
    ad.paths = sorted(frozenset(ad.nudebomb.paths))
    if ad.nudebomb.verbose:
        print(f"Config: {ad}")
    return ad.nudebomb
