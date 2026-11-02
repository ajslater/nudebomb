"""MKV Track metadata."""

import sys
from collections.abc import Mapping
from enum import StrEnum
from typing import Any

if sys.version_info >= (3, 12):
    from typing import override  # pyright: ignore[reportUnreachable]
else:
    from typing_extensions import override


class TrackType(StrEnum):
    """mkvmerge track types."""

    VIDEO = "video"
    AUDIO = "audio"
    SUBTITLES = "subtitles"


class Track:
    """MKV track metadata."""

    def __init__(self, track_data: Mapping[str, Any]) -> None:
        """Initialize."""
        self.type: str = track_data["type"]
        # mkvmerge reports an int, but every consumer builds command-line
        # strings from it.
        self.id: str = str(track_data["id"])
        self.lang: str = track_data["properties"].get("language", "und")
        self.codec: str = track_data["codec"]

    @override
    def __str__(self) -> str:
        """Represent as a string."""
        return f"Track #{self.id}: {self.lang} - {self.codec}"
