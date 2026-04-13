"""Module for reading lang files."""

from contextlib import suppress
from pathlib import Path
from typing import Final

import pycountry
from confuse import AttrDict

from nudebomb.printer import Printer

LANGS_FNS: Final = frozenset({"lang", "langs", ".lang", ".langs"})


def lang_to_alpha3(lang: str) -> str:
    """Convert a language code to ISO 639-3 (alpha3) format."""
    if not lang:
        return "und"
    match len(lang):
        case 3:
            return lang
        case 2:
            with suppress(Exception):
                if lo := pycountry.languages.get(alpha_2=lang):
                    return lo.alpha_3
        case _:
            Printer(2).warn(
                f"Languages should be in two or three letter format: {lang}"
            )
    return lang


class LangFiles:
    """Process nudebomb langfiles."""

    def __init__(self, config: AttrDict) -> None:
        """Initialize."""
        self._config: AttrDict = config
        self._lang_roots: dict[Path, set[str]] = {}
        self._languages: frozenset[str] = frozenset(
            lang_to_alpha3(lang) for lang in self._config.languages
        )
        self._printer: Printer = Printer(self._config.verbose)

    def _read_lang_file(self, path: Path, fn: str) -> None:
        langpath = path / fn
        if (
            not langpath.exists()
            or not langpath.is_file()
            or (not self._config.symlinks and langpath.is_symlink())
        ):
            # ignore is already handled before we get here in walk.py
            return
        newlangs = {
            lang_to_alpha3(lang.strip())
            for line in langpath.read_text().splitlines()
            for lang in line.strip().split(",")
            if lang.strip()
        }
        if self._config.verbose > 1:
            newlangs_str = " ,".join(sorted(newlangs))
            self._printer.config(f"Also keeping {newlangs_str} for {path}")
        self._lang_roots[path] |= newlangs

    def read_lang_files(self, path: Path) -> set[str]:
        """
        Read the lang files and parse languages.

        lang_roots is a dictionary to cache paths and languages to avoid
        reparsing the same language files.
        """
        if path not in self._lang_roots:
            self._lang_roots[path] = set()
            for fn in LANGS_FNS:
                self._read_lang_file(path, fn)

        return self._lang_roots[path]

    def found_lang_files(
        self,
        top_path: Path,
        path: Path,
    ) -> bool:
        """Return True if any lang files contributed languages for this path."""
        while True:
            if self._lang_roots.get(path):
                return True
            path = path.parent
            if path in (top_path, path.parent):
                break
        return False

    def get_langs(
        self,
        top_path: Path,
        path: Path,
    ) -> frozenset[str]:
        """Get the languages from this dir and parent dirs."""
        langs = self._languages
        while True:
            langs |= self.read_lang_files(path)
            path = path.parent
            if path in (top_path, path.parent):
                break
        return frozenset(langs)
