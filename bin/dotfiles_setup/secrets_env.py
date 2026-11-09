"""Creates ~/.config/dotfiles/secrets.env owner-only and tightens a looser one."""
from __future__ import annotations

import os
import stat
from pathlib import Path

from dotfiles_setup.rollback import RollbackLog
from dotfiles_setup.tooling import Tooling

OWNER_ONLY = 0o600
CONFIG_DIR_MODE = 0o700
GROUP_OTHER = 0o077


def secrets_path(home: Path) -> Path:
    return home / ".config/dotfiles/secrets.env"


def _create_empty(path: Path) -> None:
    os.close(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, OWNER_ONLY))


def _owned_by_user(info: os.stat_result) -> bool:
    return info.st_uid == os.geteuid()


def _usable_dir(t: Tooling, directory: Path) -> bool:
    """A symlinked ~/.config (stow) is fine; the final directory must be a real directory we own."""
    info = directory.lstat()
    if not stat.S_ISDIR(info.st_mode) or not _owned_by_user(info):
        t.logger.warn(f"{directory} is not a real directory you own; not touching secrets.env.")
        return False
    if stat.S_IMODE(info.st_mode) & GROUP_OTHER:
        t.logger.warn(f"{directory} had mode {stat.S_IMODE(info.st_mode):o}; restricting to 700.")
        directory.chmod(CONFIG_DIR_MODE)
    return True


def _make_dirs(changes: RollbackLog, directory: Path) -> None:
    missing = []
    while not (directory.exists() or directory.is_symlink()):
        missing.append(directory)
        directory = directory.parent
    for level in reversed(missing):
        level.mkdir(mode=CONFIG_DIR_MODE)
        changes.track(f"DIR_CREATED:{level}", dry_run=False)


def _open_problem(path: Path, exc: OSError) -> str:
    if isinstance(exc, FileNotFoundError):
        return "is a dangling symlink" if path.is_symlink() else "does not exist"
    return f"could not be opened ({exc.strerror})"


def _file_problem(path: Path, info: os.stat_result) -> str | None:
    kind = "symlink target" if path.is_symlink() else "file"
    if not stat.S_ISREG(info.st_mode):
        return f"{kind} is not a regular file"
    return None if _owned_by_user(info) else f"{kind} is owned by another user"


def _tighten_fd(t: Tooling, path: Path, fd: int) -> bool:
    info = os.fstat(fd)
    problem = _file_problem(path, info)
    if problem:
        t.logger.warn(f"{path} {problem}; leaving it alone, but it is not protected.")
        return False
    if stat.S_IMODE(info.st_mode) & GROUP_OTHER:
        t.logger.warn(f"{path} had mode {stat.S_IMODE(info.st_mode):04o}; restricting it to 0600.")
        os.fchmod(fd, OWNER_ONLY)
    return True


def _tighten(t: Tooling, path: Path) -> bool:
    """Opens once, following a symlink like the launcher's `stat -L`, so checks and chmod hit one inode."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NONBLOCK)
    except OSError as exc:
        t.logger.warn(f"{path} {_open_problem(path, exc)}; leaving it alone, but it is not protected.")
        return False
    try:
        return _tighten_fd(t, path, fd)
    finally:
        os.close(fd)


def _ensure(t: Tooling, changes: RollbackLog, path: Path) -> bool:
    _make_dirs(changes, path.parent)
    if not _usable_dir(t, path.parent):
        return False
    if path.exists() or path.is_symlink():
        return _tighten(t, path)
    _create_empty(path)
    changes.track(f"FILE_CREATED:{path}", dry_run=False)
    t.logger.success(f"Created {path} with mode 0600.")
    return True


def ensure_secrets_env(t: Tooling, changes: RollbackLog) -> bool:
    path = secrets_path(t.home)
    if t.logger.dry_run_notice(f"Would ensure {path} exists with mode 0600."):
        return True
    try:
        return _ensure(t, changes, path)
    except OSError as exc:
        t.logger.error(f"secrets.env setup failed: {exc}")
        return False
