"""The install: every setup step in run order, inside a sudo session and rollback log."""
from __future__ import annotations

import os
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

from dotfiles_setup import (
    apt_packages,
    apt_sources,
    claude_profile,
    claude_tools,
    desktop_defaults,
    stow,
    system_steps,
    tools,
)
from dotfiles_setup.backends import InstallResult
from dotfiles_setup.log import Logger
from dotfiles_setup.rollback import RollbackLog
from dotfiles_setup.system_steps import SudoSession, SystemContext
from dotfiles_setup.tooling import Tooling

Step = tuple[str, Callable[[], bool | None]]
INTERRUPTED_EXIT_CODE = 130


@dataclass(frozen=True)
class FlowInputs:
    t: Tooling
    dotfiles_dir: Path
    preset_name: str
    packages: frozenset[str]
    overlay_root: Path | None
    force: bool
    stamp: str
    euid: int = field(default_factory=os.geteuid)


def build_steps(inputs: FlowInputs, packages: frozenset[str], changes: RollbackLog) -> list[Step]:
    t = inputs.t
    ctx = SystemContext(t, inputs.dotfiles_dir, packages, changes)
    stow_plan = stow.StowPlan(
        t, inputs.dotfiles_dir, inputs.overlay_root, inputs.force,
        t.home / ".local/state/dotfiles/stow-backups", inputs.stamp, changes, inputs.preset_name,
    )
    return [
        ("install_core_deps", lambda: system_steps.install_core_deps(ctx)),
        ("disable_snapd", lambda: system_steps.disable_snapd(ctx)),
        ("strip_snap_from_system_path", lambda: system_steps.strip_snap_from_system_path(ctx)),
        ("configure_apt_sources", lambda: apt_sources.configure_apt_sources(ctx)),
        ("install_tools", lambda: tools.install_tools(t, packages)),
        ("install_packages", lambda: apt_packages.install_packages(ctx)),
        ("install_post_apt_tools", lambda: tools.install_post_apt_tools(t, packages)),
        ("enable_gpaste_extension", lambda: system_steps.enable_gpaste_extension(ctx)),
        ("install_github_bins", lambda: apt_packages.install_github_bins(ctx)),
        ("configure_docker_group", lambda: system_steps.configure_docker_group(ctx)),
        ("configure_dotfiles", lambda: stow.configure_dotfiles(stow_plan)),
        ("retire_claude_profile", lambda: claude_profile.retire_claude_profile(t)),
        ("configure_claude_tools", lambda: claude_tools.configure_claude_tools(t, inputs.preset_name)),
        ("change_shell", lambda: desktop_defaults.change_shell(t)),
        ("set_default_terminal", lambda: desktop_defaults.set_default_terminal(t)),
    ]


def _run_steps(steps: list[Step], logger: Logger, log: RollbackLog) -> InstallResult:
    for name, step in steps:
        if step() is False:
            message = f"Step '{name}' failed. See output above."
            return InstallResult(False, 1, message, rollback_pending=not logger.dry_run)
    log.discard()
    return InstallResult(True, 0, "")


def _start_log(inputs: FlowInputs, logger: Logger) -> RollbackLog:
    log = RollbackLog.for_home(inputs.t.home)
    if not logger.dry_run:
        pending = len(log.entries())
        if pending:
            logger.warn(f"Keeping {pending} rollback entries from an earlier unfinished run ({log.path}).")
        log.path.touch()
        logger.info(f"Rollback tracking enabled. Log: {log.path}")
    return log


@contextmanager
def _user_bin_on_path(home: Path) -> Iterator[None]:
    """pipx and cargo install into ~/.local/bin, which a later step must be able to run."""
    original = os.environ.get("PATH", "")
    os.environ["PATH"] = f"{home / '.local/bin'}:{original}"
    try:
        yield
    finally:
        os.environ["PATH"] = original


def run_install(inputs: FlowInputs) -> InstallResult:
    logger = inputs.t.logger
    if inputs.euid == 0:
        logger.error("This script must not be run as root. Use 'sudo' when prompted.")
        return InstallResult(False, 1, "Refusing to run as root.")
    packages = inputs.packages
    logger.info(f"Found {len(packages)} unique packages to install.")
    log = _start_log(inputs, logger)
    session = SudoSession(SystemContext(inputs.t, inputs.dotfiles_dir, packages, log))
    try:
        if not session.start():
            return InstallResult(False, 1, "Could not obtain sudo credentials.")
        with _user_bin_on_path(inputs.t.home):
            return _run_steps(build_steps(inputs, packages, log), logger, log)
    except KeyboardInterrupt:
        return InstallResult(False, INTERRUPTED_EXIT_CODE, "Interrupted.", rollback_pending=not logger.dry_run)
    finally:
        session.stop()


def print_completion_banner(logger: Logger) -> None:
    rule = "----------------------------------------------------"
    print()
    logger.banner(rule)
    if logger.dry_run:
        logger.banner("Dry-run complete! No changes were made.")
        logger.banner("Run without --dry-run to execute the setup.")
    else:
        logger.banner("Setup complete!")
        logger.banner("Please log out and log back in for all changes (especially the new shell) to apply.")
        logger.banner("Don't forget to manually add any secrets to ~/.config/dotfiles/secrets.env")
        logger.banner(
            "For Claude Code to control Chrome, install the 'Claude' extension from the Chrome Web Store and run "
            "'claude --chrome' once to complete onboarding (this pairing is per-machine and can't be scripted)."
        )
    logger.banner(rule)
