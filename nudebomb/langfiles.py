"""Module for reading lang files."""

import pycountry
from termcolor import cprint

LANGS_FNS = ("lang", "langs", ".lang", ".langs")


def lang_to_alpha3(lang):
    """Convert languages to ISO-639-1 (alpha2) format."""
    if not lang:
        lang = "und"
    elif len(lang) == 3:  # noqa PLR2004
        pass
    elif len(lang) == 2:  # noqa PLR2004
        try:
            if lo := pycountry.languages.get(alpha_2=lang):
                lang = lo.alpha_3
        except Exception:  # noqa
            pass
    else:
        cprint(
            f"WARNING: Languages should be in two or three letter format: {lang}",
            "yellow",
        )

    return lang


class LangFiles:
    """Process nudebomb langfiles."""

    def __init__(self, config):
        """Initialize."""
        self._config = config
        self._lang_roots = {}
        langs = set()
        for lang in self._config.languages:
            langs.add(lang_to_alpha3(lang))
        self._languages = frozenset(langs)

    def read_lang_files(self, path):
        """Read the lang files and parse languages.

        lang_roots is a dictionary to cache paths and languages to avoid
        reparsing the same language files.
        """
        if path not in self._lang_roots:
            self._lang_roots[path] = set()
            for fn in LANGS_FNS:
                langpath = path / fn
                if (
                    not langpath.exists()
                    or not langpath.is_file()
                    or (not self._config.symlinks and langpath.is_symlink())
                ):
                    # ignore is already handled before we get here in walk.py
                    continue
                newlangs = set()
                with langpath.open("r") as langfile:
                    for line in langfile:
                        for lang in line.strip().split(","):
                            newlang = lang_to_alpha3(lang.strip())
                            newlangs.add(newlang)
                if self._config.verbose:
                    newlangs_str = " ,".join(sorted(newlangs))
                    cprint(f"Also keeping {newlangs_str} for {path}", "cyan")
                self._lang_roots[path] |= newlangs

        return self._lang_roots[path]

    def get_langs(self, top_path, path):
        """Get the languages from this dir and parent dirs."""
        langs = self._languages
        while True:
            langs |= self.read_lang_files(path)
            path = path.parent
            if path in (top_path, path.parent):
                break
        return frozenset(langs)
