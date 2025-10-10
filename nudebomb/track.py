"""MKV Track metadata."""

from typing_extensions import override


class Track:
    """MKV track metadata."""

    def __init__(self, track_data):
        """Initialize."""
        self.type: str = track_data["type"]
        self.id: str = track_data["id"]
        self.lang: str = track_data["properties"].get("language", "und")
        self.codec: str = track_data["codec"]

    @override
    def __str__(self):
        """Represetnd as a string."""
        return f"Track #{self.id}: {self.lang} - {self.codec}"
