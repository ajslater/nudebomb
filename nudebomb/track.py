"""MKV Track metadata."""


class Track:
    """MKV track metadata."""

    def __init__(self, track_data):
        """Initialize."""
        self.type = track_data["type"]
        self.id = track_data["id"]
        self.lang = track_data["properties"].get("language", "und")
        self.codec = track_data["codec"]

    def __str__(self):
        """Represetnd as a string."""
        return f"Track #{self.id}: {self.lang} - {self.codec}"
