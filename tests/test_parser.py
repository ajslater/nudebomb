"""Test filename parser."""

import pytest

from nudebomb.lookup.parser import parse_title

__all__ = ()

_TV_NO_YEAR = "GI Robot Adventures - S01E02 - the killing.mkv"
_TV_WITH_YEAR = "GI Robot (2025) - S02E01-E02 - massacre.mkv"
_MOVIE = "Hedgehog Acrobats (1999) Director's Cut 1080p.mkv"


class TestParseTV:
    """TV episode parsing."""

    @pytest.mark.parametrize("media_type", ["", "tv"])
    def test_tv_no_year(self: "TestParseTV", media_type: str) -> None:
        """Parse a TV episode filename without a year."""
        result = parse_title(_TV_NO_YEAR, media_type)
        assert result.title == "GI Robot Adventures"
        assert result.year == ""

    @pytest.mark.parametrize("media_type", ["", "tv"])
    def test_tv_with_year_and_multi_episode_marker(
        self: "TestParseTV", media_type: str
    ) -> None:
        """Parse a TV episode filename with a year and an S01E02-E03 range."""
        result = parse_title(_TV_WITH_YEAR, media_type)
        assert result.title == "GI Robot"
        assert result.year == "2025"


class TestParseMovie:
    """Movie parsing."""

    @pytest.mark.parametrize("media_type", ["", "movie"])
    def test_movie_with_year_and_quality_tag(
        self: "TestParseMovie", media_type: str
    ) -> None:
        """Parse a movie filename with a year and a quality tag."""
        result = parse_title(_MOVIE, media_type)
        assert result.title == "Hedgehog Acrobats"
        assert result.year == "1999"
