"""System-level steps that need root. A step returns False to stop the run and records its changes for rollback."""
from __future__ import annotations

import getpass
import shutil
import threading
import time
from collections.abc import Collection
from dataclasses import dataclass
from pathlib import Path

from dotfiles_setup.rollback import RollbackLog
from dotfiles_setup.tooling import Tooling, dry_run_all

CORE_PACKAGES = ("curl", "gpg", "stow", "zsh", "wget", "sed", "build-essential")
GPASTE_ID = "GPaste@gnome-shell-extensions.gnome.org"
SUDO_REFRESH_SECONDS = 60


@dataclass(frozen=True)
class SystemContext:
    t: Tooling
    dotfiles_dir: Path
    packages: Collection[str]
    changes: RollbackLog

    def quiet(self, *argv: str, cwd: Path | None = None) -> bool:
        return self.t.logger.quiet_run(list(argv), run=self.t.run, cwd=cwd).returncode == 0

    def track(self, entry: str) -> None:
        self.changes.track(entry, dry_run=self.t.logger.dry_run)


class SudoSession:
    """Keeps sudo credentials fresh for the length of a run."""

    def __init__(self, ctx: SystemContext) -> None:
        self._ctx = ctx
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._refresh, daemon=True)

    def _refresh(self) -> None:
        while not self._stop.wait(SUDO_REFRESH_SECONDS):
            self._ctx.t.run(["sudo", "-n", "true"], capture_output=True)

    def start(self) -> bool:
        t = self._ctx.t
        t.logger.info("This script requires sudo access to install packages and configure the system.")
        if dry_run_all(t, "Would verify sudo credentials and start refresh loop"):
            return True
        if t.run(["sudo", "-v"]).returncode != 0:
            t.logger.error("Sudo password entry failed or was cancelled.")
            return False
        self._thread.start()
        t.logger.step("Sudo credentials verified. Starting setup...")
        return True

    def stop(self) -> None:
        self._stop.set()


def install_core_deps(ctx: SystemContext) -> bool:
    t = ctx.t
    t.logger.step("Step 1: Installing core dependencies (curl, gpg, stow, zsh)...")
    if dry_run_all(t, f"Would install: {', '.join(CORE_PACKAGES)}"):
        return True
    if not ctx.quiet("sudo", "apt-get", "install", "-y", *CORE_PACKAGES):
        return False
    t.logger.success("Core dependencies installed.")
    return True


def _installed_snaps(ctx: SystemContext) -> list[str]:
    listing = ctx.t.run(["snap", "list", "--all"], capture_output=True, text=True).stdout or ""
    return [line.split()[0] for line in listing.splitlines()[1:] if line.strip()]


def _remove_snaps(ctx: SystemContext) -> bool:
    logger = ctx.t.logger
    snaps = _installed_snaps(ctx)
    if snaps:
        logger.info(f"Removing {len(snaps)} snap packages...")
    else:
        logger.info("No snap packages found to remove.")
    for snap in snaps:
        logger.info(f"Removing snap package: {snap}")
        if not ctx.quiet("sudo", "snap", "remove", "--purge", snap):
            logger.warn(f"Failed to remove snap package '{snap}'. Continuing...")
    logger.info("Removing snapd apt package...")
    if not ctx.quiet("sudo", "apt-get", "remove", "-y", "--purge", "snapd"):
        logger.warn("Failed to remove snapd apt package (it may be already removed).")
    if not ctx.quiet("sudo", "apt-get", "-y", "autoremove", "--purge"):
        return False
    logger.success("Snapd and all snap packages removed.")
    return True


def _has_snap() -> bool:
    return shutil.which("snap") is not None


def disable_snapd(ctx: SystemContext) -> bool:
    logger = ctx.t.logger
    logger.step("Step 2: Disabling and removing snapd...")
    logger.info("Stowing 'system' package to / to block snapd...")
    if dry_run_all(ctx.t, "Would stow 'system' package to / (includes snapd block preferences)"):
        removal = "Would remove snap packages and snapd" if _has_snap() else "Snapd not installed, would skip removal"
        dry_run_all(ctx.t, removal)
        return True
    stowed = ctx.quiet(
        "sudo", "stow", f"--dir={ctx.dotfiles_dir}", "--restow", "--target=/", "--verbose=1", "system",
        cwd=ctx.dotfiles_dir,
    )
    if stowed:
        ctx.track("STOW_ROOT:system")
    if not _has_snap():
        logger.info("Snapd is not installed. Skipping removal.")
        return True
    return _remove_snaps(ctx)


def strip_snap_from_system_path(ctx: SystemContext, env_file: Path = Path("/etc/environment")) -> bool:
    logger = ctx.t.logger
    logger.step("Step 2b: Removing /snap/bin from the system PATH...")
    if not _mentions_snap(env_file):
        logger.info(f"No /snap/bin in {env_file}. Skipping.")
        return True
    if dry_run_all(ctx.t, f"Would back up {env_file} and remove /snap/bin from its PATH"):
        return True
    backup = f"{env_file}.backup-{int(time.time())}"
    if not ctx.quiet("sudo", "cp", "-a", str(env_file), backup):
        return False
    ctx.track(f"FILE_BACKUP:{backup}")
    # Strip the colon along with the entry: a bare '' element in PATH means the cwd.
    if not ctx.quiet("sudo", "sed", "-i", "-e", "s#:/snap/bin##g", "-e", "s#/snap/bin:##g", str(env_file)):
        return False
    if _mentions_snap(env_file):
        logger.warn(f"Could not remove /snap/bin from {env_file} (is it the only PATH entry?). Left as-is.")
        return True
    logger.success(f"/snap/bin removed from {env_file} (backup: {backup}).")
    logger.warn("Log out and back in for the new system PATH to apply.")
    return True


def _mentions_snap(env_file: Path) -> bool:
    try:
        return "/snap/bin" in env_file.read_text()
    except OSError:
        return False


def enable_gpaste_extension(ctx: SystemContext) -> None:
    logger = ctx.t.logger
    if "gnome-shell-extension-gpaste" not in ctx.packages:
        return
    logger.step("Step 4b: Enabling GPaste GNOME Shell extension...")
    if shutil.which("gnome-extensions") is None:
        logger.warn("gnome-extensions command not found. Skipping GPaste extension enable.")
    elif dry_run_all(ctx.t, f"Would enable {GPASTE_ID}"):
        return
    elif ctx.t.run(["gnome-extensions", "enable", GPASTE_ID], capture_output=True).returncode == 0:
        logger.success("GPaste extension enabled.")
    else:
        logger.warn("Failed to enable GPaste extension (no active GNOME Shell session?).")
        logger.warn(f"Enable it manually with: gnome-extensions enable {GPASTE_ID}")


def _docker_group_exists(ctx: SystemContext) -> bool:
    return ctx.t.run(["getent", "group", "docker"], capture_output=True).returncode == 0


def _user_in_docker_group(ctx: SystemContext, user: str) -> bool:
    groups = ctx.t.run(["groups", user], capture_output=True, text=True).stdout or ""
    return "docker" in groups.replace(":", " ").split()


def configure_docker_group(ctx: SystemContext, user: str | None = None) -> bool:
    if "docker-ce" not in ctx.packages:
        return True
    logger = ctx.t.logger
    user = user or getpass.getuser()
    logger.step("Step 6: Configuring docker group...")
    if logger.dry_run:
        if not _docker_group_exists(ctx):
            logger.dry_run_notice("Would create docker group")
        if _user_in_docker_group(ctx, user):
            logger.info(f"User {user} is already in docker group.")
        else:
            logger.dry_run_notice(f"Would add user {user} to docker group")
        return True
    if not _docker_group_exists(ctx):
        logger.info("Creating docker group...")
        if ctx.t.run(["sudo", "groupadd", "docker"]).returncode != 0:
            return False
    if _user_in_docker_group(ctx, user):
        logger.info(f"User {user} is already in docker group.")
        return True
    logger.info(f"Adding user {user} to docker group...")
    if ctx.t.run(["sudo", "usermod", "-aG", "docker", user]).returncode != 0:
        return False
    ctx.track(f"DOCKER_GROUP:{user}")
    logger.success("User added to docker group.")
    return True
