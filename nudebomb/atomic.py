"""Atomic file writes."""

import uuid
from contextlib import suppress
from pathlib import Path

__all__ = ("atomic_write_text",)


def atomic_write_text(path: Path, content: str, mode: int | None = None) -> None:
    """
    Write ``content`` to ``path`` via a tmp file + rename.

    Each write is all-or-nothing — readers never see a half-written file,
    and a crash leaves the previous contents intact. A uuid4 suffix keeps
    concurrent writers to the same target from clobbering each other's tmp
    files; the final ``replace`` is atomic so last-writer-wins is the worst
    case. ``mode`` is applied to the tmp file before the rename, so the
    target is never briefly more permissive than asked.
    """
    tmp_path = path.with_suffix(f"{path.suffix}.{uuid.uuid4().hex}.tmp")
    try:
        tmp_path.write_text(content)
        if mode is not None:
            # Best effort: filesystems without POSIX modes just skip it.
            with suppress(OSError):
                tmp_path.chmod(mode)
        tmp_path.replace(path)
    except OSError:
        tmp_path.unlink(missing_ok=True)
        raise
