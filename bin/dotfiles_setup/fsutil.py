"""Crash-safe file writes: the target path always holds either its old or its new content."""
from __future__ import annotations

import os
import shutil
import tempfile
import uuid
from pathlib import Path

from dotfiles_setup.result import Err, Ok, Result


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


def install_executable(source: Path, target: Path) -> None:
    """Atomically replace `target` with a mode 0755 copy of `source`; the target's directory must exist."""
    descriptor, name = tempfile.mkstemp(dir=target.parent, prefix=f"{target.name}.", suffix=".tmp")
    staged = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as out, source.open("rb") as incoming:
            shutil.copyfileobj(incoming, out)
            out.flush()
            os.fsync(out.fileno())
        staged.chmod(0o755)
    except BaseException:
        staged.unlink(missing_ok=True)
        raise
    commit_staged(staged, target)


def link_executable(real: Path, name: str, bin_dir: Path) -> Result[Path]:
    """Atomically point `bin_dir/name` at the absolute form of `real`, replacing only a symlink; a file or directory there is kept and reported as Err. A file that appears between the check and the replace may be overwritten."""
    link, real = bin_dir / name, Path(os.path.abspath(real))
    if link.exists(follow_symlinks=False) and not link.is_symlink():
        return Err(f"{link} exists and is not a symlink; leaving it in place.")
    staged = bin_dir / f".{name}.{uuid.uuid4().hex}.tmp"
    try:
        staged.symlink_to(real)
        commit_staged(staged, link)
    except OSError as error:
        staged.unlink(missing_ok=True)
        return Err(f"Could not link {link} to {real}: {error}")
    return Ok(link)


def atomic_write_text(path: Path, text: str, mode: int) -> None:
    commit_staged(stage_text(path, text, mode), path)


def _copy_exclusive(source: Path, destination: Path) -> bool:
    try:
        os.close(os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600))
    except FileExistsError:
        return False
    try:
        shutil.copy2(source, destination)
    except BaseException:
        destination.unlink(missing_ok=True)
        raise
    return True


def _claim(source: Path, destination: Path) -> bool:
    """Create `destination` as a copy of `source` without replacing anything; False when the name is taken."""
    try:
        os.link(source, destination)
        return True
    except FileExistsError:
        return False
    except OSError:
        return _copy_exclusive(source, destination)


def keep_copy(source: Path, wanted: Path) -> Path:
    """Preserve `source` under `wanted` (suffixed -1, -2 on a collision) without ever removing `source`."""
    candidates = (wanted, *(wanted.with_name(f"{wanted.name}-{n}") for n in range(1, 1000)))
    return next(c for c in candidates if _claim(source, c))
