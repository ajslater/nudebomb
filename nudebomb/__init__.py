"""Nudebomb."""

from os import environ

PROGRAM_NAME = "nudebomb"
if environ.get("PYTHONDEVMODE"):
    from icecream import install  # pyright: ignore[reportPrivateImportUsage]

    install()
