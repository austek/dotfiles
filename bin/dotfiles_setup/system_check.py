"""Read-only check for whether the sudo-requiring system stage has anything left to do."""
from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from dotfiles_setup import (
    antigravity,
    apt_packages,
    desktop_defaults,
    release_installers,
    system_steps,
)
from dotfiles_setup.plan_types import StepPlan
from dotfiles_setup.system_steps import SystemContext

NOSNAP_PREFERENCE = Path("/etc/apt/preferences.d/nosnap.pref")
STATUS_FORMAT = "-f=${db:Status-Abbrev} ${Package}\\n"
DOCKER_REASON = "the docker group is not set up"
SHELL_REASON = "the login shell is not zsh"
REASON_ORDER = ("apt", "removals", "snapd", "github debs", "system releases", "docker group", "login shell")


def _installed_packages(ctx: SystemContext) -> set[str]:
    listing = ctx.t.run(["dpkg-query", "-W", STATUS_FORMAT], capture_output=True, text=True).stdout or ""
    return {line.split()[1] for line in listing.splitlines() if line.startswith("ii ") and len(line.split()) > 1}


def apt_reason(missing: Sequence[str]) -> str | None:
    return f"{len(missing)} apt package(s) not installed ({', '.join(missing[:3])}...)" if missing else None


def debs_reason(missing: Sequence[str]) -> str | None:
    return f"{len(missing)} GitHub .deb package(s) missing or outdated" if missing else None


def releases_reason(missing: Sequence[str]) -> str | None:
    return f"{len(missing)} release tool(s) not installed ({', '.join(missing)})" if missing else None


def snapd_reason(installed: set[str], nosnap: Path = NOSNAP_PREFERENCE) -> str | None:
    if "snapd" in installed:
        return "snapd is installed"
    return None if nosnap.exists() else "the snapd block preference is missing"


def pending_releases(ctx: SystemContext) -> list[str]:
    """Wanted sudo-installed release tools that are absent or not the pinned build."""
    missing = release_installers.pending_system_releases(ctx.t, ctx.packages)
    return [*missing, "antigravity-ide"] if "antigravity-ide" in ctx.packages and antigravity.pending() else missing


def _missing_apt_packages(ctx: SystemContext, installed: set[str]) -> str | None:
    wanted = {p for p in ctx.packages if apt_packages.is_apt_package(p)} | set(system_steps.CORE_PACKAGES)
    return apt_reason(sorted(wanted - installed))


def _pending_removals(ctx: SystemContext, installed: set[str]) -> str | None:
    from dotfiles_setup.removals import (  # removals imports this module's STATUS_FORMAT
        dpkg_name,
        split_removals,
    )

    split = split_removals(tuple(ctx.removals))
    pending = installed & {*split.apt, *(dpkg_name(entry) for entry in split.debs)}
    return f"{len(pending)} apt package(s) pending removal" if pending else None


def _planned_reasons(ctx: SystemContext, plans: Sequence[StepPlan]) -> list[str]:
    """Reasons read off the plan rows; removals are the approved ones, known only after the plan is confirmed."""
    by_step = {plan.step: plan.reason for plan in plans if plan.needs_sudo}
    live = _pending_removals(ctx, _installed_packages(ctx)) if ctx.removals else None
    reasons = (live if step == "removals" else by_step.get(step) for step in REASON_ORDER)
    return [reason for reason in reasons if reason]


def system_stage_reasons(
    ctx: SystemContext, nosnap: Path = NOSNAP_PREFERENCE, plans: Sequence[StepPlan] = (),
) -> list[str]:
    if plans:
        return _planned_reasons(ctx, plans)
    installed = _installed_packages(ctx)
    checks = (
        _missing_apt_packages(ctx, installed),
        _pending_removals(ctx, installed),
        snapd_reason(installed, nosnap),
        debs_reason(apt_packages.pending_github_bins(ctx)),
        releases_reason(pending_releases(ctx)),
        DOCKER_REASON if system_steps.docker_group_pending(ctx) else None,
        SHELL_REASON if desktop_defaults.shell_change_pending() else None,
    )
    return [reason for reason in checks if reason]
