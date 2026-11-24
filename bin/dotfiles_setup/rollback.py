"""Rollback log: each change a setup run makes is appended as `ACTION:data`,
and a failed run can undo them newest first."""
from __future__ import annotations

import errno
import hashlib
import os
import shutil
import stat
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from dotfiles_setup.tooling import Tooling

LOG_NAME = ".dotfiles-setup-rollback.log"


@dataclass(frozen=True)
class RollbackLog:
    path: Path

    @staticmethod
    def for_home(home: Path) -> RollbackLog:
        return RollbackLog(home / LOG_NAME)

    def track(self, entry: str, *, dry_run: bool) -> None:
        if not dry_run:
            with self.path.open("a") as handle:
                handle.write(f"{entry}\n")

    def entries(self) -> list[str]:
        if not self.path.is_file():
            return []
        return [line for line in self.path.read_text().splitlines() if line]

    def discard(self) -> None:
        self.path.unlink(missing_ok=True)

    def has_entries(self) -> bool:
        return self.path.is_file() and self.path.stat().st_size > 0


@dataclass(frozen=True)
class RollbackContext:
    t: Tooling
    log: RollbackLog
    dotfiles_dir: Path
    overlay_root: Path | None


def _run_quiet(ctx: RollbackContext, argv: list[str], cwd: Path | None = None) -> bool:
    result = ctx.t.run(argv, capture_output=True, text=True, cwd=cwd)
    return result.returncode == 0


def _unstow(ctx: RollbackContext, label: str, data: str, root: Path | None, sudo: bool = False) -> None:
    ctx.t.logger.info(label)
    if root is None:
        ctx.t.logger.warn(f"Failed to unstow {data}")
        return
    target = "/" if sudo else str(ctx.t.home)
    argv = [*(["sudo"] if sudo else []), "stow", "--delete", f"--target={target}", data]
    if not _run_quiet(ctx, argv, cwd=root):
        ctx.t.logger.warn(f"Failed to unstow {data}")


def _restow_overlay(ctx: RollbackContext, data: str) -> None:
    ctx.t.logger.info(f"Restoring overlay package links to HOME: {data}")
    argv = ["stow", "--restow", "--no-folding", f"--target={ctx.t.home}", data]
    if ctx.overlay_root is None or not _run_quiet(ctx, argv, cwd=ctx.overlay_root):
        ctx.t.logger.warn(f"Failed to restow {data}")


def _restore_backup(ctx: RollbackContext, data: str) -> None:
    """The entry is `backup|original`; a bare `backup` sits next to the original with a `.backup-<ts>` suffix."""
    backup, _, recorded = data.partition("|")
    original = recorded or backup.rsplit(".backup-", 1)[0]
    if Path(backup).is_file() or Path(backup).is_symlink():
        ctx.t.logger.info(f"Restoring backed up file: {original}")
        if not _run_quiet(ctx, ["sudo", "mv", backup, original]):
            ctx.t.logger.warn(f"Failed to restore {original}")


def _stow_home(ctx: RollbackContext, data: str) -> None:
    _unstow(ctx, f"Unstowing package from HOME: {data}", data, ctx.dotfiles_dir)


def _stow_overlay(ctx: RollbackContext, data: str) -> None:
    _unstow(ctx, f"Unstowing overlay package from HOME: {data}", data, ctx.overlay_root)


def _stow_root(ctx: RollbackContext, data: str) -> None:
    _unstow(ctx, f"Unstowing package from /: {data}", data, ctx.dotfiles_dir, sudo=True)


def _docker_group(ctx: RollbackContext, data: str) -> None:
    ctx.t.logger.info("Removing user from docker group")
    if not _run_quiet(ctx, ["sudo", "gpasswd", "-d", data, "docker"]):
        ctx.t.logger.warn("Failed to remove user from docker group")


def _file_created(ctx: RollbackContext, data: str) -> None:
    ctx.t.logger.info(f"Removing generated file: {data}")
    if not _run_quiet(ctx, ["sudo", "rm", "-f", data]):
        ctx.t.logger.warn(f"Failed to remove {data}")


def _dir_created(ctx: RollbackContext, data: str) -> None:
    ctx.t.logger.info(f"Removing generated directory if empty: {data}")
    try:
        Path(data).rmdir()
    except FileNotFoundError:
        return
    except OSError as exc:
        log = ctx.t.logger.info if exc.errno == errno.ENOTEMPTY else ctx.t.logger.warn
        log(f"Kept {data}: {exc}")


def _binary_installed(ctx: RollbackContext, data: str) -> None:
    path, _, digest = data.rpartition("|")
    target = Path(path)
    try:
        held = _hold(ctx, target, stat.S_ISREG, "regular file")
    except _HoldFailed:
        return
    if held is None:
        return
    try:
        matches = hashlib.sha256(held.read_bytes()).hexdigest() == digest
    except OSError as exc:
        ctx.t.logger.warn(f"Kept {target}: could not read it: {exc}")
        _put_back(ctx, held, target)
        return
    if matches:
        ctx.t.logger.info(f"Removing installed binary: {target}")
        if not _discard(ctx, held):
            _put_back(ctx, held, target)
    else:
        ctx.t.logger.info(f"Kept {target}: it changed since the install.")
        _put_back(ctx, held, target)


class _HoldFailed(Exception):
    """`_hold` left the path in place and has already said why."""


def _hold(ctx: RollbackContext, path: Path, is_kind: Callable[[int], bool], kind: str) -> Path | None:
    """Moves `path` into a new private directory beside it and returns the new location, or None when `path` is missing. Only an object whose mode satisfies `is_kind` is moved; raises `_HoldFailed` after logging for any other object or error."""
    try:
        if not is_kind(path.lstat().st_mode):
            ctx.t.logger.info(f"Kept {path}: it is not a {kind}.")
            raise _HoldFailed
    except FileNotFoundError:
        return None
    except OSError as exc:
        ctx.t.logger.warn(f"Failed to remove {path}: {exc}")
        raise _HoldFailed from exc
    try:
        held_dir = Path(tempfile.mkdtemp(dir=path.parent, prefix=f".{path.name}.rollback-"))
    except FileNotFoundError:
        return None
    except OSError as exc:
        ctx.t.logger.warn(f"Failed to remove {path}: {exc}")
        raise _HoldFailed from exc
    held = held_dir / path.name
    try:
        os.replace(path, held)
    except OSError as exc:
        try:
            held_dir.rmdir()
        except OSError as cleanup:
            ctx.t.logger.warn(f"Could not remove the empty directory {held_dir}: {cleanup}")
        if isinstance(exc, FileNotFoundError):
            return None
        ctx.t.logger.warn(f"Failed to remove {path}: {exc}")
        raise _HoldFailed from exc
    return held


def _discard(ctx: RollbackContext, held: Path) -> bool:
    """Deletes `held`; False, with a warning, when that fails. A holding directory that cannot be removed afterwards is only a warning."""
    try:
        held.unlink()
    except OSError as exc:
        ctx.t.logger.warn(f"Could not delete {held}: {exc}")
        return False
    try:
        held.parent.rmdir()
    except OSError as exc:
        ctx.t.logger.warn(f"Could not remove the empty directory {held.parent}: {exc}")
    return True


def _put_back(ctx: RollbackContext, held: Path, target: Path) -> None:
    """Restores `held` to `target` as a hard link and never overwrites an existing target. A newer target or any other failure warns and keeps `held` in its directory; success removes both."""
    try:
        os.link(held, target, follow_symlinks=False)
    except FileExistsError:
        ctx.t.logger.warn(f"A newer {target} exists; the previous file is kept at {held}")
        return
    except OSError as exc:
        ctx.t.logger.warn(f"Could not restore {target}: {exc}; the file is kept at {held}")
        return
    _discard(ctx, held)


def _points_into(held: Path, original: Path, root: Path) -> bool:
    """True when the held symlink, read as if it still sat at `original`, resolves into `root`."""
    try:
        resolved = (original.parent / os.readlink(held)).resolve()
        return resolved.is_relative_to(root.resolve())
    except (OSError, RuntimeError):
        return False


def _link_installed(ctx: RollbackContext, data: str) -> bool:
    """True when the link is gone or was ours and is now removed; a replaced object is put back, or kept in its holding directory, and reported as False."""
    root_text, _, rest = data.partition("|")
    root, link = Path(root_text), Path(rest.partition("|")[0])
    try:
        held = _hold(ctx, link, stat.S_ISLNK, "symlink")
    except _HoldFailed:
        return False
    if held is None:
        return True
    if _points_into(held, link, root):
        if _discard(ctx, held):
            return True
    else:
        ctx.t.logger.info(f"Kept {link}: it is not a symlink into {root}.")
    _put_back(ctx, held, link)
    return False


def _identity(path: Path) -> str:
    status = path.lstat()
    return f"{status.st_dev}:{status.st_ino}"


def _tree_state(ctx: RollbackContext, root: Path, recorded: str) -> str:
    """`owned` when `root` is the directory the install created (recorded device and inode), `missing` when it is gone, else `foreign`."""
    try:
        owned = _identity(root) == recorded and stat.S_ISDIR(root.lstat().st_mode)
    except FileNotFoundError:
        return "missing"
    except OSError as exc:
        ctx.t.logger.warn(f"Could not inspect {root}: {exc}")
        return "foreign"
    return "owned" if owned else "foreign"


def _tree_installed(ctx: RollbackContext, data: str) -> None:
    """The entry is `root|link|dev:ino`, the last field absent in logs older than the identity check. Ownership is checked first: when the tree's device and inode do not match, both the tree and the link stay. Otherwise the link rule applies and the tree is removed once the link is gone or was ours and is now removed."""
    root_text, _, rest = data.partition("|")
    link_text, _, recorded = rest.partition("|")
    root = Path(root_text)
    state = _tree_state(ctx, root, recorded)
    if state == "foreign":
        ctx.t.logger.info(f"Kept {root} and {link_text}: ownership could not be verified.")
        return
    if not _link_installed(ctx, data) or state == "missing":
        return
    ctx.t.logger.info(f"Removing installed tree: {root}")
    try:
        shutil.rmtree(root)
    except OSError as exc:
        ctx.t.logger.warn(f"Failed to remove {root}: {exc}")


def _link_only_installed(ctx: RollbackContext, data: str) -> None:
    _link_installed(ctx, data)


def _apt_removed(ctx: RollbackContext, data: str) -> None:
    ctx.t.logger.info(f"Reinstalling removed package: {data}")
    if not _run_quiet(ctx, ["sudo", "apt-get", "install", "-y", data]):
        ctx.t.logger.warn(f"Failed to reinstall {data}")


def _deb_removed(ctx: RollbackContext, data: str) -> None:
    ctx.t.logger.warn(f"Removed {data} is not in apt; reinstall {data} manually.")


def _overlay_moved(ctx: RollbackContext, data: str) -> None:
    """The entry is `old|new`. Moves the overlay back and relinks it from the old path."""
    # Imported here because overlay_migrate imports this module.
    from dotfiles_setup import overlay_migrate

    old_text, _, new_text = data.partition("|")
    old, new = Path(old_text), Path(new_text)
    if old.exists() or not new.is_dir():
        ctx.t.logger.warn(f"Failed to move {new} back to {old}")
        return
    ctx.t.logger.info(f"Moving the overlay back: {new} to {old}")
    if overlay_migrate.relocate(ctx.t, new, old) is not overlay_migrate.Relocation.MOVED:
        ctx.t.logger.warn(f"Failed to move {new} back to {old}")


def _flatpak_removed(ctx: RollbackContext, data: str) -> None:
    ctx.t.logger.info(f"Reinstalling removed Flatpak app: {data}")
    argv = ["flatpak", "install", "--user", "-y", "--noninteractive", "flathub", data]
    if not _run_quiet(ctx, argv):
        ctx.t.logger.warn(f"Failed to reinstall {data}")


# The *_PRIVATE names are written to rollback logs on disk, so they keep their spelling after the overlay rename.
_UNDO_HANDLERS: dict[str, Callable[[RollbackContext, str], None]] = {
    "STOW_HOME": _stow_home,
    "STOW_PRIVATE": _stow_overlay,
    "UNSTOW_PRIVATE": _restow_overlay,
    "OVERLAY_MOVED": _overlay_moved,
    "STOW_ROOT": _stow_root,
    "DOCKER_GROUP": _docker_group,
    "FILE_BACKUP": _restore_backup,
    "FILE_CREATED": _file_created,
    "DIR_CREATED": _dir_created,
    "BIN_INSTALLED": _binary_installed,
    "TERMINFO_INSTALLED": _binary_installed,
    "TREE_INSTALLED": _tree_installed,
    "LINK_INSTALLED": _link_only_installed,
    "APT_REMOVED": _apt_removed,
    "DEB_REMOVED": _deb_removed,
    "FLATPAK_REMOVED": _flatpak_removed,
}


def _undo(ctx: RollbackContext, entry: str) -> None:
    action, _, data = entry.partition(":")
    handler = _UNDO_HANDLERS.get(action)
    if handler is None:
        ctx.t.logger.warn(f"Unknown rollback action: {action}")
        return
    handler(ctx, data)


def perform_rollback(ctx: RollbackContext) -> None:
    logger = ctx.t.logger
    if not ctx.log.has_entries():
        logger.info("No rollback log found. Nothing to roll back.")
        return
    banner = "=========================================="
    for line in (banner, "Setup failed. Rolling back changes...", banner):
        logger.warn(line)
    for entry in reversed(ctx.log.entries()):
        _undo(ctx, entry)
    logger.success("Rollback completed.")
    logger.info("Removing rollback log...")
    ctx.log.discard()
    logger.warn("Note: Installed packages (apt, snap) were NOT removed during rollback.")
    logger.warn("You may want to remove them manually if needed.")


def offer_rollback(
    ctx: RollbackContext, interactive: bool, ask: Callable[[str], str] = input,
) -> None:
    logger = ctx.t.logger
    if not ctx.log.has_entries():
        return
    logger.warn("Setup did not complete successfully.")
    logger.warn(f"A rollback log has been created at: {ctx.log.path}")
    if not interactive:
        logger.info("Non-interactive mode: Skipping rollback prompt.")
        logger.info(f"You can manually roll back by reviewing: {ctx.log.path}")
    elif ask("Do you want to roll back changes? (y/N): ").strip().lower().startswith("y"):
        perform_rollback(ctx)
    else:
        logger.info(f"Rollback skipped. You can review the log at: {ctx.log.path}")
