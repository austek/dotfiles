"""Removes apt packages and Flatpak apps the user opted out of, recording each removal for rollback."""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from dotfiles_setup import flatpak
from dotfiles_setup.apt_packages import CUSTOM_INSTALL_PACKAGES, is_apt_package
from dotfiles_setup.rollback import RollbackLog
from dotfiles_setup.system_check import STATUS_FORMAT
from dotfiles_setup.system_steps import SystemContext
from dotfiles_setup.tooling import Tooling


@dataclass(frozen=True)
class Split:
    apt: tuple[str, ...]
    flatpak: tuple[str, ...]
    manual: tuple[str, ...]


def split_removals(pending: Sequence[str]) -> Split:
    return Split(
        apt=tuple(n for n in pending if is_apt_package(n)),
        flatpak=tuple(n.removeprefix(flatpak.PREFIX) for n in pending if flatpak.is_flatpak_entry(n)),
        manual=tuple(n for n in pending if n in CUSTOM_INSTALL_PACKAGES),
    )


def _installed_apt(t: Tooling) -> set[str]:
    listing = t.run(["dpkg-query", "-W", STATUS_FORMAT], capture_output=True, text=True).stdout or ""
    return {line.split()[1] for line in listing.splitlines() if line.startswith("ii ") and len(line.split()) > 1}


def _flatpak_installed(t: Tooling, app_id: str) -> bool:
    return t.run(["flatpak", "info", "--user", app_id], capture_output=True).returncode == 0


def installed_only(t: Tooling, split: Split) -> Split:
    present = _installed_apt(t) if split.apt else set()
    return Split(
        apt=tuple(n for n in split.apt if n in present),
        flatpak=tuple(i for i in split.flatpak if _flatpak_installed(t, i)),
        manual=split.manual,
    )


def _would_remove(ctx: SystemContext, name: str) -> set[str] | None:
    """Packages the simulation removes, or None when it failed or never lists `name`."""
    result = ctx.t.run(["apt-get", "-s", "remove", "-y", name], capture_output=True, text=True)
    lines = (result.stdout or "").splitlines()
    listed = {line.split()[1] for line in lines if line.startswith("Remv ") and len(line.split()) > 1}
    return listed if result.returncode == 0 and name in listed else None


def _remove_one_apt(ctx: SystemContext, name: str) -> bool:
    listed = _would_remove(ctx, name)
    if listed is None:
        ctx.t.logger.warn(f"Skipping {name}: apt simulation failed.")
        return False
    extras = listed - {name}
    if extras:
        ctx.t.logger.warn(f"Skipping {name}: removing it would also remove {', '.join(sorted(extras))}.")
        return False
    if not ctx.quiet("sudo", "apt-get", "remove", "-y", name):
        ctx.t.logger.warn(f"Failed to remove {name}.")
        return False
    ctx.track(f"APT_REMOVED:{name}")
    return True


def remove_apt(ctx: SystemContext, names: Sequence[str]) -> list[str]:
    return [name for name in names if _remove_one_apt(ctx, name)]


def _remove_one_flatpak(t: Tooling, changes: RollbackLog, app_id: str) -> bool:
    argv = ["flatpak", "uninstall", "--user", "-y", "--noninteractive", app_id]
    if t.logger.quiet_run(argv, run=t.run).returncode != 0:
        t.logger.warn(f"Failed to remove Flatpak app {app_id}.")
        return False
    changes.track(f"FLATPAK_REMOVED:{app_id}", dry_run=t.logger.dry_run)
    return True


def remove_flatpaks(t: Tooling, changes: RollbackLog, ids: Sequence[str]) -> list[str]:
    return [app_id for app_id in ids if _remove_one_flatpak(t, changes, app_id)]
