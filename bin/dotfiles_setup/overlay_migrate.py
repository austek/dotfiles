"""Moves a legacy ~/.dotfiles-private overlay to ~/.dotfiles-overlay and relinks it, unstowing it from the old path first."""
from __future__ import annotations

import os
import re
from pathlib import Path

from dotfiles_setup import overlay, stow, worktree
from dotfiles_setup.rollback import RollbackLog
from dotfiles_setup.tooling import Tooling, dry_run_all

_PACKAGE_FILE = re.compile(r"^\.stow-packages(\.[A-Za-z0-9_-]+)?$")


def _overridden(t: Tooling) -> bool:
    """An override variable pins the overlay's location, so nothing is moved; the legacy one is reported."""
    if os.environ.get(overlay.OVERLAY_ROOT_VARIABLE):
        return True
    if os.environ.get(overlay.LEGACY_ROOT_VARIABLE):
        t.logger.warn(f"{overlay.LEGACY_ROOT_VARIABLE} is deprecated; set {overlay.OVERLAY_ROOT_VARIABLE} instead.")
        return True
    return False


def _stow_packages(root: Path) -> list[str]:
    """Package directories named by .stow-packages and .stow-packages.<preset>; stow refuses a whole call over a missing one."""
    files = (path for path in root.iterdir() if _PACKAGE_FILE.match(path.name) and path.is_file())
    names = {name for path in files for name in stow.package_lines(path)}
    return sorted(name for name in names if Path(name).name == name and (root / name).is_dir())


def _unstow(t: Tooling, root: Path, packages: list[str]) -> bool:
    argv = ["stow", "--delete", f"--target={t.home}", stow.VERBOSE_FLAG, *packages]
    return not packages or t.logger.quiet_run(argv, run=t.run, cwd=root).returncode == 0


def _restow(t: Tooling, root: Path, packages: list[str]) -> None:
    argv = ["stow", "--restow", "--no-folding", f"--target={t.home}", *packages]
    if packages and t.logger.quiet_run(argv, run=t.run, cwd=root).returncode != 0:
        t.logger.warn(f"Could not restow {' '.join(packages)} from {root}; re-run dfctl apply to link them.")


def _repair_worktrees(t: Tooling, root: Path) -> None:
    """Linked worktrees keep an absolute path to the checkout's .git, which a move leaves stale."""
    if (root / ".git").is_dir() and t.logger.quiet_run(["git", "-C", str(root), "worktree", "repair"], run=t.run).returncode != 0:
        t.logger.warn(f"Could not repair the linked worktrees of {root}; run `git -C {root} worktree repair`.")


def _repoint_gitconfig_local(t: Tooling, source: Path, target: Path) -> None:
    link = t.home / ".gitconfig.local"
    if not link.is_symlink():
        return
    try:
        relative = Path(os.readlink(link)).relative_to(source)
        link.unlink()
        link.symlink_to(target / relative)
    except ValueError:
        return
    except OSError as error:
        t.logger.warn(f"Could not repoint {link} to {target} ({error}); re-run dfctl apply.")


def _move(t: Tooling, src: Path, dst: Path, packages: list[str]) -> bool:
    try:
        src.rename(dst)
    except OSError as error:
        t.logger.error(f"Could not move {src} to {dst} ({error}); restoring its links.")
        _restow(t, src, packages)
        return False
    return True


def relocate(t: Tooling, src: Path, dst: Path) -> bool:
    """Unstows src, renames it to dst, repairs its linked worktrees, repoints ~/.gitconfig.local and restows from dst."""
    packages = _stow_packages(src)
    if not _unstow(t, src, packages):
        t.logger.error(f"Could not unstow {src}; leaving it in place. Fix the conflict above and re-run.")
        return False
    if not _move(t, src, dst, packages):
        return False
    _repair_worktrees(t, dst)
    _repoint_gitconfig_local(t, src, dst)
    _restow(t, dst, packages)
    return True


def _release_leftover(t: Tooling, legacy: Path, new: Path) -> None:
    """With both checkouts present the new one is used, so the old one's links would only conflict."""
    t.logger.warn(f"Both {legacy} and {new} exist; using {new}. Move what you still need out of {legacy} and remove it.")
    if dry_run_all(t, f"Would unstow the links that still point into {legacy}"):
        return
    if not _unstow(t, legacy, _stow_packages(legacy)):
        t.logger.warn(f"Could not unstow {legacy}; apply may report stow conflicts until its links are removed.")


def _refuse_worktree(t: Tooling, legacy: Path, new: Path) -> bool:
    if dry_run_all(t, f"Would refuse to move {legacy}: it is a linked worktree"):
        return True
    t.logger.error(f"{legacy} is a linked worktree; move the main overlay checkout to {new} instead.")
    return False


def migrate_legacy_overlay(t: Tooling, changes: RollbackLog) -> bool:
    """Returns False when the worktree check, the unstow or the move fails; the install then stops."""
    legacy, new = overlay.LEGACY_OVERLAY_ROOT, overlay.DEFAULT_OVERLAY_ROOT
    if _overridden(t) or not legacy.is_dir():
        return True
    if new.exists() or new.is_symlink():
        _release_leftover(t, legacy, new)
        return True
    if worktree.is_linked_worktree(legacy):
        return _refuse_worktree(t, legacy, new)
    if dry_run_all(t, f"Would unstow the packages of {legacy}, move it to {new} and restow them"):
        return True
    if not relocate(t, legacy, new):
        return False
    changes.track(f"OVERLAY_MOVED:{legacy}|{new}", dry_run=False)
    t.logger.success(f"Moved {legacy} to {new} and relinked its packages.")
    return True
