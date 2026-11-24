"""Read-only plan rows for the system, user-tool and config steps; each reads local state only."""
from __future__ import annotations

from collections.abc import Collection
from pathlib import Path

from dotfiles_setup import (
    claude_profile,
    desktop_defaults,
    release_installers,
    secrets_env,
    stow,
    system_check,
    system_steps,
    terminfo,
    tools,
    user_links,
    zsh_cache,
)
from dotfiles_setup.plan_types import StepPlan
from dotfiles_setup.rollback import RollbackLog
from dotfiles_setup.system_steps import SystemContext
from dotfiles_setup.tooling import Tooling

NO_SYSTEM_NOTE = "skipped: --no-system"
UPGRADE_CHECK_NOTE = "pinned upgrades are checked during apply"


def _sudo_row(step: str, system: str, change: tuple[str, ...], reason: str | None) -> StepPlan:
    if system == "never":
        return StepPlan(step, 0, 0, note=NO_SYSTEM_NOTE)
    return StepPlan(step, 0, 0, change=change, needs_sudo=True, reason=reason)


def _snapd_row(installed: set[str], system: str) -> StepPlan:
    reason = system_check.snapd_reason(installed)
    return _sudo_row("snapd", system, (reason,) if reason else (), reason)


def _releases_row(ctx: SystemContext, system: str) -> StepPlan:
    if system == "never":
        return StepPlan("system releases", 0, 0, note=NO_SYSTEM_NOTE)
    missing = tuple(system_check.pending_releases(ctx))
    return StepPlan(
        "system releases", 0, 0, install=missing, needs_sudo=True, reason=system_check.releases_reason(missing),
    )


def system_rows(ctx: SystemContext, installed: set[str], system: str) -> tuple[StepPlan, ...]:
    docker = system_steps.docker_group_pending(ctx)
    shell = desktop_defaults.shell_change_pending()
    return (
        _snapd_row(installed, system),
        _releases_row(ctx, system),
        _sudo_row("docker group", system, (system_check.DOCKER_REASON,) if docker else (), system_check.DOCKER_REASON if docker else None),
        _sudo_row("login shell", system, (system_check.SHELL_REASON,) if shell else (), system_check.SHELL_REASON if shell else None),
    )


def _tools_row(t: Tooling, packages: Collection[str], upgrade: bool) -> StepPlan:
    missing = (*tools.pending_tools(t, packages), *release_installers.pending_user_binaries(t, packages))
    return StepPlan("user tools", 0, 0, install=missing, note=UPGRADE_CHECK_NOTE if upgrade else None)


def _stow_plan(t: Tooling, dotfiles_dir: Path, overlay_root: Path | None, preset_name: str) -> stow.StowPlan:
    return stow.StowPlan(t, dotfiles_dir, overlay_root, False, t.home, "", RollbackLog.for_home(t.home), preset_name)


def user_rows(
    t: Tooling, dotfiles_dir: Path, packages: Collection[str], overlay_root: Path | None, preset_name: str,
    upgrade: bool,
) -> tuple[StepPlan, ...]:
    links = stow.pending_links(_stow_plan(t, dotfiles_dir, overlay_root, preset_name))
    return (
        _tools_row(t, packages, upgrade),
        StepPlan("user links", 0, 0, change=user_links.pending(t, packages)),
        StepPlan("terminfo", 0, 0, change=terminfo.pending(t)),
        StepPlan("dotfiles links", 0, 0, change=links),
        StepPlan("zsh completion cache", 0, 0, change=("drop the completion dump",) if zsh_cache.pending(t.home) else ()),
        StepPlan("secrets.env", 0, 0, change=secrets_env.pending(t.home)),
        StepPlan("claude profile", 0, 0, change=tuple(f"remove {p}" for p in claude_profile.pending_files(t.home))),
        StepPlan("ibus hotkey", 0, 0, change=("free Ctrl+Shift+U",) if desktop_defaults.ibus_hotkey_pending(t) else ()),
    )
