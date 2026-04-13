"""Filename parsing for media language lookups."""

import re
from dataclasses import dataclass
from typing import Final

# Looks for a 4-digit year (1900-2099)
_YEAR_PATTERN: Final = re.compile(r"\b\(((?:1[89]|20)\d{2})\)\b")

# TV episode markers: S01E02, 1x02, etc.
_EPISODE_PATTERN: Final = re.compile(
    r"\b[Ss]\d+[Ee]\d+\b|\b\d+[Xx]\d+\b",
)

_IGNORE_PATTERN: Final = re.compile(
    r"-(?:behindthescenes|deleted|featurette|interview|scene|short|trailer|other)$",
    re.IGNORECASE,
)

# General noise markers to truncate the title if no year is found
_NOISE_CUTOFF: Final = re.compile(
    r"""(?ix)
    \b(s\d+e\d+|\d+x\d+|480p|720p|1080p|2160p|4k|uhd|hdtv|bluray|web-?dl|remux|x264|h264|x265|hevc)\b|[\[\(\{]
    """,
)

_DELIMITERS: Final = re.compile(r"[._\s]+")

# ID tags in curly braces: {tmdb-272}, {imdb-tt0372784}, {tvdb-12345}
_TMDB_ID_PATTERN: Final = re.compile(r"\{tmdb-(\d+)\}")
_IMDB_ID_PATTERN: Final = re.compile(r"\{imdb-(tt\d+)\}")
_TVDB_ID_PATTERN: Final = re.compile(r"\{tvdb-(\d+)\}")
# Any curly-brace tag (for stripping after ID extraction)
_BRACE_TAG_PATTERN: Final = re.compile(r"\{[^}]*\}")


@dataclass(frozen=True, slots=True)
class ParseResult:
    """Result of parsing a media filename."""

    title: str
    year: str
    tmdb_id: str
    imdb_id: str
    tvdb_id: str


def _strip_extension(filename: str) -> str:
    """Strip file extension."""
    return filename.rsplit(".", 1)[0]


def _extract_ids(stem: str) -> tuple[str, str, str, str]:
    """Extract TMDB/IMDB/TVDB IDs and return (cleaned_stem, tmdb_id, imdb_id, tvdb_id)."""
    tmdb_id = ""
    imdb_id = ""
    tvdb_id = ""
    if tmdb_match := _TMDB_ID_PATTERN.search(stem):
        tmdb_id = tmdb_match.group(1)
    if imdb_match := _IMDB_ID_PATTERN.search(stem):
        imdb_id = imdb_match.group(1)
    if tvdb_match := _TVDB_ID_PATTERN.search(stem):
        tvdb_id = tvdb_match.group(1)

    # Strip all curly-brace tags
    cleaned = _BRACE_TAG_PATTERN.sub("", stem)
    return cleaned, tmdb_id, imdb_id, tvdb_id


def _strip_noise_from_title(normalized: str) -> str:
    # No episode marker found; fall back to noise cutoff
    if noise_match := _NOISE_CUTOFF.search(normalized):
        title = normalized[: noise_match.start()]
    else:
        title = normalized
    return title


def _parse_title_without_noise(normalized: str) -> tuple[str, str]:
    title = normalized
    year = ""

    year_match = _YEAR_PATTERN.search(normalized)
    if year_match:
        year = year_match.group(1)
        title = normalized[: year_match.start()]

    # Strip trailing punctuation like "(" left over from "(2024)"
    clean_title = title.strip().rstrip("(").strip()
    return clean_title, year


def _parse_tv_episode_matched_title(normalized: str) -> str:
    episode_match = _EPISODE_PATTERN.search(normalized)
    if episode_match:
        # Series name is everything before the " - S01E02" segment.
        # Walk backwards from the episode match to find the separator.
        return normalized[: episode_match.start()].strip()
    return ""


def _parse_tv_title(normalized: str) -> tuple[str, str]:
    """Extract TV series name by truncating before the episode marker."""
    title = _parse_tv_episode_matched_title(normalized)
    if not title:
        title = _strip_noise_from_title(normalized)
    return _parse_title_without_noise(title)


def _parse_movie_title(normalized: str) -> tuple[str, str]:
    """Extract movie title and year."""
    title = _strip_noise_from_title(normalized)
    return _parse_title_without_noise(title)


def _parse_generic_title(normalized: str) -> tuple[str, str]:
    """Parse title when media type is unknown. Detect TV patterns first."""
    if title := _parse_tv_episode_matched_title(normalized):
        return _parse_title_without_noise(title)

    # Fall back to movie-style parsing
    return _parse_movie_title(normalized)


def parse_title(filename: str, media_type: str = "") -> ParseResult:
    """Parse title, year, and IDs from a media filename."""
    stem = _strip_extension(filename)

    # Extract IDs before normalizing
    stem, tmdb_id, imdb_id, tvdb_id = _extract_ids(stem)

    # If we have an ID, we can skip title parsing entirely
    if tmdb_id or imdb_id or tvdb_id:
        return ParseResult(
            title="", year="", tmdb_id=tmdb_id, imdb_id=imdb_id, tvdb_id=tvdb_id
        )

    normalized = _DELIMITERS.sub(" ", stem).strip()

    if _IGNORE_PATTERN.search(normalized):
        return ParseResult(title="", year="", tmdb_id="", imdb_id="", tvdb_id="")

    match media_type:
        case "tv":
            title, year = _parse_tv_title(normalized)
        case "movie":
            title, year = _parse_movie_title(normalized)
        case _:
            title, year = _parse_generic_title(normalized)

    return ParseResult(title=title, year=year, tmdb_id="", imdb_id="", tvdb_id="")
