"""Rollback log shared with bin/lib/rollback.sh: each change a setup run makes
is appended as `ACTION:data`, and a failed run can undo them newest first.
The shell segments and the Python hooks write to the same file."""
from __future__ import annotations

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


def _restore_backup(ctx: RollbackContext, data: str) -> None:
    original = data.rsplit(".backup-", 1)[0]
    if Path(data).is_file():
        ctx.t.logger.info(f"Restoring backed up file: {original}")
        if not _run_quiet(ctx, ["sudo", "mv", data, original]):
            ctx.t.logger.warn(f"Failed to restore {original}")


def _undo(ctx: RollbackContext, entry: str) -> None:
    action, _, data = entry.partition(":")
    logger = ctx.t.logger
    if action == "STOW_HOME":
        _unstow(ctx, f"Unstowing package from HOME: {data}", data, ctx.dotfiles_dir)
    elif action == "STOW_PRIVATE":
        _unstow(ctx, f"Unstowing private-overlay package from HOME: {data}", data, ctx.private_root)
    elif action == "STOW_ROOT":
        _unstow(ctx, f"Unstowing package from /: {data}", data, ctx.dotfiles_dir, sudo=True)
    elif action == "DOCKER_GROUP":
        logger.info("Removing user from docker group")
        if not _run_quiet(ctx, ["sudo", "gpasswd", "-d", data, "docker"]):
            logger.warn("Failed to remove user from docker group")
    elif action == "FILE_BACKUP":
        _restore_backup(ctx, data)
    elif action == "FILE_CREATED":
        logger.info(f"Removing generated file: {data}")
        if not _run_quiet(ctx, ["sudo", "rm", "-f", data]):
            logger.warn(f"Failed to remove {data}")
    else:
        logger.warn(f"Unknown rollback action: {action}")


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
    ctx.log.path.unlink(missing_ok=True)
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
