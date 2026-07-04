"""Module for reading lang files."""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from loguru import logger

from nudebomb.lang import lang_to_alpha3

if TYPE_CHECKING:
    from pathlib import Path

    from nudebomb.config import NudebombSettings
    from nudebomb.log.summary import Stats

__all__ = ("LANGS_FNS", "LangFiles", "lang_to_alpha3")

LANGS_FNS: Final = frozenset({"lang", "langs", ".lang", ".langs"})


class LangFiles:
    """Process nudebomb langfiles."""

    def __init__(self, config: NudebombSettings, stats: Stats | None = None) -> None:
        """Initialize."""
        self._config: NudebombSettings = config
        self._lang_roots: dict[Path, set[str]] = {}
        self._languages: frozenset[str] = frozenset(
            lang_to_alpha3(lang) for lang in self._config.languages
        )
        self._stats: Stats | None = stats

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
        newlangs_str = ", ".join(sorted(newlangs))
        logger.info(f"Also keeping {newlangs_str} for {path}")
        if self._stats is not None and newlangs:
            self._stats.record_langfile_hit()
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
        # Check the boundary only after visiting the current dir so
        # top_path's own lang files count for nested paths too.
        while True:
            if self._lang_roots.get(path):
                return True
            if path in (top_path, path.parent):
                break
            path = path.parent
        return False

    def _collect_lang_files(self, top_path: Path, path: Path) -> set[str]:
        """Union the languages from this dir up to (and including) top_path."""
        langs: set[str] = set()
        # Check the boundary only after visiting the current dir so
        # top_path's own lang files apply to nested paths too.
        while True:
            langs |= self.read_lang_files(path)
            if path in (top_path, path.parent):
                break
            path = path.parent
        return langs

    def get_langs(
        self,
        top_path: Path,
        path: Path,
    ) -> frozenset[str]:
        """Get the base languages plus those from this dir and parent dirs."""
        return frozenset(self._languages | self._collect_lang_files(top_path, path))

    def get_extra_langs(
        self,
        top_path: Path,
        path: Path,
    ) -> frozenset[str]:
        """
        Get only the languages contributed by lang files up the tree.

        Unlike :meth:`get_langs`, the base ``--languages`` set is not seeded
        in, so callers can union these purely-additive langfile languages
        onto a per-directory resolved keep-set (see
        :class:`nudebomb.dirconfig.DirConfig`) instead of the global one.
        """
        return frozenset(self._collect_lang_files(top_path, path))
