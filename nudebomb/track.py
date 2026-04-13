"""MKV Track metadata."""

from collections.abc import Mapping
from typing import Any

from typing_extensions import override


class Track:
    """MKV track metadata."""

    def __init__(self, track_data: Mapping[str, Any]) -> None:
        """Initialize."""
        self.type: str = track_data["type"]
        self.id: int = track_data["id"]
        self.lang: str = track_data["properties"].get("language", "und")
        self.codec: str = track_data["codec"]

    @override
    def __str__(self) -> str:
        """Represent as a string."""
        return f"Track #{self.id}: {self.lang} - {self.codec}"
