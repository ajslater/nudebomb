"""Utility functions for the lookup module."""

from nudebomb.langfiles import lang_to_alpha3


def resolve_language(result: dict) -> str | None:
    """Extract and convert language from a TMDB result."""
    lang_2 = result.get("original_language")
    if not lang_2:
        return None
    return lang_to_alpha3(lang_2)


def format_title_year(title: str, year: str) -> str:
    """Format title string for log messages."""
    return f"{title} ({year})" if year else title
