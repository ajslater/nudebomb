"""
Language-code utilities.

Lives in its own module so both ``nudebomb.config`` and
``nudebomb.langfiles`` can depend on it without forming an import
cycle (``langfiles`` takes ``NudebombSettings`` for type-checking;
``config`` previously imported ``lang_to_alpha3`` from ``langfiles``,
which would close the loop).
"""

from __future__ import annotations

from contextlib import suppress

import pycountry
from loguru import logger


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
            logger.warning(f"Languages should be in two or three letter format: {lang}")
    return lang
