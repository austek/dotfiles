"""Read-only plans for every apply step: local reads only, no sudo, no network, no writes."""
from __future__ import annotations

import os
import shutil
from collections.abc import Collection, Sequence
from pathlib import Path

from dotfiles_setup import (
    apt_packages,
    config_plans,
    flatpak,
    overlay,
    overlay_migrate,
    removals,
    system_check,
    system_steps,
)
from dotfiles_setup.plan_types import StepPlan, unknown_step
from dotfiles_setup.rollback import RollbackLog
from dotfiles_setup.system_steps import SystemContext
from dotfiles_setup.tooling import Tooling

NO_SYSTEM_NOTE = config_plans.NO_SYSTEM_NOTE
OVERLAY_DEFER_NOTE = "the legacy overlay stays where it is until stow is installed"
UPGRADE_CHANGE = "apt dist-upgrade and flatpak update (package list is from the local apt cache)"
FLATPAK_UPDATE_CHANGE = "update all Flatpak apps"
SKIP_FLATPAK_NOTE = f"skipped: {flatpak.SKIP_ENV} is set"
APT_SOURCES = "apt sources"
POST_APT_TOOLS = "post-apt tools"
CLAUDE_TOOLS = "claude tools"
GITHUB_DEBS = "github debs"
UNKNOWN_ROWS = {
    APT_SOURCES: "keys, PPAs and source files",
    POST_APT_TOOLS: "auditr, cargo crates and the GPaste extension",
    CLAUDE_TOOLS: "tool and plugin installs, and the stale-copy report",
    "default terminal": "alternatives, xdg lists and gsettings",
}
# Every step in install_flow.build_steps needs an entry here, or a plan-guided dry run drops it.
STEP_ROWS = {
    "install_core_deps": "apt", "disable_snapd": "snapd", "strip_snap_from_system_path": "snapd",
    "configure_apt_sources": APT_SOURCES, "install_tools": "user tools", "install_user_binaries": "user tools",
    "link_user_tools": "user links", "install_ghostty_terminfo": "terminfo", "install_system_tools": "system releases",
    "install_packages": "apt", "upgrade_packages": "apt", "report_upgradable": "apt", "install_flatpaks": "flatpak",
    "remove_flatpaks": "removals", "remove_apt_packages": "removals", "report_unremoved": "removals",
    "report_skipped_sources": APT_SOURCES, "install_post_apt_tools": POST_APT_TOOLS,
    "enable_gpaste_extension": POST_APT_TOOLS, "install_github_bins": GITHUB_DEBS,
    "configure_docker_group": "docker group", "configure_dotfiles": "dotfiles links",
    "refresh_zsh_completion_cache": "zsh completion cache", "ensure_secrets_env": "secrets.env",
    "retire_claude_profile": "claude profile", "configure_claude_tools": CLAUDE_TOOLS,
    "report_stale_copies": CLAUDE_TOOLS, "change_shell": "login shell",
    "set_default_terminal": "default terminal", "disable_ibus_unicode_hotkey": "ibus hotkey",
}


def _context(t: Tooling, dotfiles_dir: Path, wanted: Collection[str]) -> SystemContext:
    return SystemContext(t, dotfiles_dir, wanted, RollbackLog.for_home(t.home))


def _apt_plan(ctx: SystemContext, installed: set[str], system: str, upgrade: bool) -> StepPlan:
    wanted = sorted({*(p for p in ctx.packages if apt_packages.is_apt_package(p)), *system_steps.CORE_PACKAGES})
    if system == "never":
        return StepPlan("apt", len(wanted), 0, note=NO_SYSTEM_NOTE)
    missing = tuple(p for p in wanted if p not in installed)
    upgrades = (apt_packages.upgradable_names(ctx) or ()) if upgrade else ()
    return StepPlan(
        "apt", len(wanted), len(wanted) - len(missing), install=missing, upgrade=upgrades,
        change=(UPGRADE_CHANGE,) if upgrade else (), needs_sudo=True, reason=system_check.apt_reason(missing),
    )


def _flatpak_plan(t: Tooling, packages: Collection[str], upgrade: bool) -> StepPlan:
    ids = flatpak.app_ids(packages)
    if os.environ.get(flatpak.SKIP_ENV):
        return StepPlan("flatpak", len(ids), 0, note=SKIP_FLATPAK_NOTE)
    missing = flatpak.missing_ids(t, packages)
    change = (FLATPAK_UPDATE_CHANGE,) if upgrade else ()
    return StepPlan("flatpak", len(ids), len(ids) - len(missing), install=missing, change=change)


def _debs_plan(ctx: SystemContext, system: str) -> StepPlan:
    wanted = sum(1 for p in ctx.packages if p.startswith(apt_packages.PIN_PREFIX))
    if system == "never":
        return StepPlan(GITHUB_DEBS, wanted, 0, note=NO_SYSTEM_NOTE)
    pending = tuple(apt_packages.pending_github_bins(ctx))
    return StepPlan(
        GITHUB_DEBS, wanted, wanted - len(pending), install=pending,
        needs_sudo=True, reason=system_check.debs_reason(pending),
    )


def _removable(pending: Sequence[str], system: str) -> tuple[str, ...]:
    manual = set(removals.split_removals(pending).manual)
    entries = tuple(name for name in pending if name not in manual)
    if system != "never":
        return entries
    return tuple(name for name in entries if flatpak.is_flatpak_entry(name))


def _removals_plan(pending: Sequence[str], system: str, prune: bool) -> StepPlan:
    removable = _removable(pending, system)
    return StepPlan("removals", 0, 0, remove=removable if prune else (), held=() if prune else removable)


def _overlay_plan() -> StepPlan | None:
    legacy, new = overlay.LEGACY_OVERLAY_ROOT, overlay.DEFAULT_OVERLAY_ROOT
    match overlay_migrate.pending_migration():
        case overlay_migrate.Migration.MOVE if shutil.which("stow") is None and overlay_migrate.needs_stow(legacy):
            return StepPlan("overlay", 0, 0, note=OVERLAY_DEFER_NOTE)
        case overlay_migrate.Migration.MOVE:
            return StepPlan("overlay", 0, 0, change=(f"move {legacy} to {new}",))
        case overlay_migrate.Migration.LEFTOVER:
            return StepPlan("overlay", 0, 0, note=f"both {legacy} and {new} exist; {new} is used")
        case overlay_migrate.Migration.REFUSE_WORKTREE:
            return StepPlan("overlay", 0, 0, note=f"{legacy} is a linked worktree; apply refuses to move it")
        case _:
            return None


def build_step_plans(
    t: Tooling, dotfiles_dir: Path, wanted: frozenset[str], pending: Sequence[str],
    *, upgrade: bool, prune: bool, system: str, overlay_root: Path | None, preset_name: str,
) -> tuple[StepPlan, ...]:
    ctx = _context(t, dotfiles_dir, wanted)
    installed = system_check._installed_packages(ctx) if system != "never" else set()
    return (
        *filter(None, (_overlay_plan(),)),
        _apt_plan(ctx, installed, system, upgrade),
        _flatpak_plan(t, wanted, upgrade),
        _debs_plan(ctx, system),
        _removals_plan(pending, system, prune),
        *config_plans.system_rows(ctx, installed, system),
        *config_plans.user_rows(t, dotfiles_dir, wanted, overlay_root, preset_name, upgrade),
        *(unknown_step(step, note) for step, note in UNKNOWN_ROWS.items()),
    )
