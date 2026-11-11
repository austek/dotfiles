"""Rollback log: each change a setup run makes is appended as `ACTION:data`,
and a failed run can undo them newest first."""
from __future__ import annotations

import errno
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
    private_root: Path | None


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


def _restow_private(ctx: RollbackContext, data: str) -> None:
    ctx.t.logger.info(f"Restoring private-overlay package links to HOME: {data}")
    argv = ["stow", "--restow", "--no-folding", f"--target={ctx.t.home}", data]
    if ctx.private_root is None or not _run_quiet(ctx, argv, cwd=ctx.private_root):
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


def _stow_private(ctx: RollbackContext, data: str) -> None:
    _unstow(ctx, f"Unstowing private-overlay package from HOME: {data}", data, ctx.private_root)


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


def _apt_removed(ctx: RollbackContext, data: str) -> None:
    ctx.t.logger.info(f"Reinstalling removed package: {data}")
    if not _run_quiet(ctx, ["sudo", "apt-get", "install", "-y", data]):
        ctx.t.logger.warn(f"Failed to reinstall {data}")


def _deb_removed(ctx: RollbackContext, data: str) -> None:
    ctx.t.logger.warn(f"Removed {data} is not in apt; reinstall {data} manually.")


def _flatpak_removed(ctx: RollbackContext, data: str) -> None:
    ctx.t.logger.info(f"Reinstalling removed Flatpak app: {data}")
    argv = ["flatpak", "install", "--user", "-y", "--noninteractive", "flathub", data]
    if not _run_quiet(ctx, argv):
        ctx.t.logger.warn(f"Failed to reinstall {data}")


_UNDO_HANDLERS: dict[str, Callable[[RollbackContext, str], None]] = {
    "STOW_HOME": _stow_home,
    "STOW_PRIVATE": _stow_private,
    "UNSTOW_PRIVATE": _restow_private,
    "STOW_ROOT": _stow_root,
    "DOCKER_GROUP": _docker_group,
    "FILE_BACKUP": _restore_backup,
    "FILE_CREATED": _file_created,
    "DIR_CREATED": _dir_created,
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
