"""Utility functions."""

from dataclasses import dataclass, field

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


@dataclass(frozen=True, slots=True)
class LogEvent:
    """
    A deferred Printer call from a worker thread.

    The main thread replays these against the real Printer after awaiting
    the lookup future, keeping all output serialized on one thread.
    """

    method: str
    message: str


@dataclass(frozen=True, slots=True)
class LookupResult:
    """
    The outcome of a language lookup.

    ``events`` holds the log calls the worker would have made on the Printer.
    """

    lang: str | None = None
    events: tuple[LogEvent, ...] = field(default_factory=tuple)
