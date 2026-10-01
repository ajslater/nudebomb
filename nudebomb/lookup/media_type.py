"""Remote DB media types."""

from enum import StrEnum
from typing import Final


class MediaType(StrEnum):
    """
    Media type namespaces for lookups and the lookup cache.

    Settings keep ``media_type`` as a plain ``str``: members compare and hash
    equal to their values, but ruamel can't represent them when writing
    config or timestamp files.
    """

    MOVIE = "movie"
    TV = "tv"


# ``value in MediaType`` raises TypeError for non-members before Python 3.12.
MEDIA_TYPES: Final = frozenset(MediaType)
