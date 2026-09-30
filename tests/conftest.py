"""Fixtures shared across the test suite."""

from pathlib import Path

import pytest

from nudebomb.lookup.cache import LookupCache

__all__ = ()


@pytest.fixture
def tmp_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> LookupCache:
    """Build a LookupCache rooted at a temp dir so tests are isolated."""
    monkeypatch.setattr(
        "nudebomb.lookup.cache.user_cache_dir",
        lambda _prog: str(tmp_path),
    )
    return LookupCache(cache_expiry_days=30)
