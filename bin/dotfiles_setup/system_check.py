"""Read-only check for whether the sudo-requiring system stage has anything left to do."""
from __future__ import annotations

from pathlib import Path

from dotfiles_setup import apt_packages, desktop_defaults, system_steps
from dotfiles_setup.system_steps import SystemContext

NOSNAP_PREFERENCE = Path("/etc/apt/preferences.d/nosnap.pref")
STATUS_FORMAT = "-f=${db:Status-Abbrev} ${Package}\\n"


def _installed_packages(ctx: SystemContext) -> set[str]:
    listing = ctx.t.run(["dpkg-query", "-W", STATUS_FORMAT], capture_output=True, text=True).stdout or ""
    return {line.split()[1] for line in listing.splitlines() if line.startswith("ii ") and len(line.split()) > 1}


def _missing_apt_packages(ctx: SystemContext, installed: set[str]) -> str | None:
    wanted = {p for p in ctx.packages if p not in apt_packages.CUSTOM_INSTALL_PACKAGES}
    missing = sorted(wanted - installed)
    return f"{len(missing)} apt package(s) not installed ({', '.join(missing[:3])}...)" if missing else None


def _snapd_state(installed: set[str], nosnap: Path) -> str | None:
    if "snapd" in installed:
        return "snapd is installed"
    return None if nosnap.exists() else "the snapd block preference is missing"


def _missing_debs(ctx: SystemContext) -> str | None:
    missing = apt_packages.missing_github_bins(ctx)
    return f"{len(missing)} GitHub .deb package(s) not installed" if missing else None


def system_stage_reasons(ctx: SystemContext, nosnap: Path = NOSNAP_PREFERENCE) -> list[str]:
    installed = _installed_packages(ctx)
    checks = (
        _missing_apt_packages(ctx, installed),
        _snapd_state(installed, nosnap),
        _missing_debs(ctx),
        "the docker group is not set up" if system_steps.docker_group_pending(ctx) else None,
        "the login shell is not zsh" if desktop_defaults.shell_change_pending() else None,
    )
    return [reason for reason in checks if reason]
