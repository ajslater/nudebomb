"""Utility functions for the lookup module."""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import TYPE_CHECKING, Final

from nudebomb.lang import lang_to_alpha3

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

# Applied to every HTTP call the lookup backends make; without it a
# stalled connection blocks a lookup thread (or startup) forever.
LOOKUP_TIMEOUT_SECONDS: Final = 30

# Minimum fuzzy similarity for accepting a search result whose title is
# not an exact normalized match for the query.
_MATCH_RATIO: Final = 0.8

_API_KEY_PATTERN: Final = re.compile(r"(api_key=)[^&\s'\"]+")

_NON_WORD_PATTERN: Final = re.compile(r"[^\w]+")


def resolve_tmdb_language(result: dict) -> str | None:
    """Extract and convert language from a TMDB result."""
    lang_2 = result.get("original_language")
    if not lang_2:
        return None
    return lang_to_alpha3(lang_2)


def format_title_year(title: str, year: str) -> str:
    """Format title string for log messages."""
    return f"{title} ({year})" if year else title


def redact_api_key(text: str) -> str:
    """Blank out api_key query parameters embedded in exception text."""
    return _API_KEY_PATTERN.sub(r"\1REDACTED", text)


def normalize_title(title: str) -> str:
    """Lowercase and strip all non-word characters for title comparison."""
    return _NON_WORD_PATTERN.sub("", title.lower())


def best_title_match(
    results: Sequence[dict],
    query_title: str,
    query_year: str,
    get_title: Callable[[dict], str],
    get_year: Callable[[dict], str],
) -> dict | None:
    """
    Return the result whose title best matches the query, or None.

    Search APIs rank fuzzily; taking their first result blind can cache
    the wrong media's language permanently. Prefer exact normalized
    title matches, then fuzzy ones, disambiguating by year when the
    filename provided one. No acceptable match returns None so the
    query records as a miss instead of poisoning the cache.
    """
    query_norm = normalize_title(query_title)
    if not query_norm:
        return None
    exact, fuzzy = _classify_matches(results, query_norm, get_title)
    for tier in (exact, fuzzy):
        if tier:
            return _pick_by_year(tier, query_year, get_year)
    return None


def _classify_matches(
    results: Sequence[dict],
    query_norm: str,
    get_title: Callable[[dict], str],
) -> tuple[list[dict], list[dict]]:
    """Split results into exact and fuzzy normalized-title matches."""
    exact: list[dict] = []
    fuzzy: list[dict] = []
    for result in results:
        result_norm = normalize_title(get_title(result))
        if not result_norm:
            continue
        if result_norm == query_norm:
            exact.append(result)
        elif SequenceMatcher(None, query_norm, result_norm).ratio() >= _MATCH_RATIO:
            fuzzy.append(result)
    return exact, fuzzy


def _pick_by_year(
    tier: list[dict],
    query_year: str,
    get_year: Callable[[dict], str],
) -> dict:
    """Prefer the result matching the query year, else the first."""
    if query_year:
        for result in tier:
            if get_year(result) == query_year:
                return result
    return tier[0]
