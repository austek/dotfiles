"""Crash-safe file writes: the target path always holds either its old or its new content."""
from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path


def stage_text(path: Path, text: str, mode: int) -> Path:
    """Write `text` durably to a temp file beside `path`; the caller commits or discards it."""
    descriptor, name = tempfile.mkstemp(dir=path.parent, prefix=f"{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as staged:
            staged.write(text)
            staged.flush()
            os.fsync(staged.fileno())
        os.chmod(name, mode)
    except BaseException:
        Path(name).unlink(missing_ok=True)
        raise
    return Path(name)


def _sync_directory(directory: Path) -> None:
    try:
        descriptor = os.open(directory, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    except OSError:
        pass
    finally:
        os.close(descriptor)


def commit_staged(staged: Path, target: Path) -> None:
    """Atomically replace `target` (or a symlink at it) with `staged`; discard `staged` on failure."""
    try:
        os.replace(staged, target)
    except BaseException:
        staged.unlink(missing_ok=True)
        raise
    _sync_directory(target.parent)


def atomic_write_text(path: Path, text: str, mode: int) -> None:
    commit_staged(stage_text(path, text, mode), path)


def _free_name(wanted: Path) -> Path:
    candidates = (wanted, *(wanted.with_name(f"{wanted.name}-{n}") for n in range(1, 1000)))
    return next(c for c in candidates if not os.path.lexists(c))


def keep_copy(source: Path, wanted: Path) -> Path:
    """Preserve `source` under `wanted` (suffixed -1, -2 on a collision) without ever removing `source`."""
    destination = _free_name(wanted)
    try:
        os.link(source, destination)
    except OSError:
        shutil.copy2(source, destination)
    return destination
