"""MKV Track metadata."""

from typing_extensions import override


class Track:
    """MKV track metadata."""

    def __init__(self, track_data: dict[str, dict[str, str] | str]) -> None:
        """Initialize."""
        self.type: str = track_data["type"]  #  pyright: ignore[reportAttributeAccessIssue]
        self.id: str = track_data["id"]  #  pyright: ignore[reportAttributeAccessIssue]
        self.lang: str = track_data["properties"].get("language", "und")  #  pyright: ignore[reportAttributeAccessIssue]
        self.codec: str = track_data["codec"]  #  pyright: ignore[reportAttributeAccessIssue]

    @override
    def __str__(self) -> str:
        """Represetnd as a string."""
        return f"Track #{self.id}: {self.lang} - {self.codec}"
