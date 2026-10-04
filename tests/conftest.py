"""Fixtures shared across the test suite."""

import os
import socket
from collections.abc import Iterator
from pathlib import Path

import pytest
import tmdbsimple

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


@pytest.fixture
def doctor_isolation(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[None]:
    """Isolate doctor config and cache, and restore the globals probes set."""
    for key in list(os.environ):
        if key.startswith("NUDEBOMB"):
            monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("NUDEBOMBDIR", str(tmp_path / "config"))
    monkeypatch.setattr(
        "nudebomb.doctor.user_cache_dir", lambda _prog: str(tmp_path / "cache")
    )
    monkeypatch.setattr(tmdbsimple, "API_KEY", tmdbsimple.API_KEY)
    monkeypatch.setattr(tmdbsimple, "REQUESTS_TIMEOUT", tmdbsimple.REQUESTS_TIMEOUT)
    old_timeout = socket.getdefaulttimeout()
    yield
    socket.setdefaulttimeout(old_timeout)
