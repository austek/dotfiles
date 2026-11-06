"""Removes apt packages and Flatpak apps the user opted out of, recording each removal for rollback."""
from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from dotfiles_setup import flatpak
from dotfiles_setup.apt_packages import (
    CUSTOM_INSTALL_PACKAGES,
    DPKG_BACKED_CUSTOM,
    PIN_PREFIX,
    is_apt_package,
)
from dotfiles_setup.result import Err, Ok, Result
from dotfiles_setup.rollback import RollbackLog
from dotfiles_setup.system_check import STATUS_FORMAT
from dotfiles_setup.system_steps import SystemContext
from dotfiles_setup.tooling import Tooling


@dataclass(frozen=True)
class Split:
    apt: tuple[str, ...]
    flatpak: tuple[str, ...]
    manual: tuple[str, ...]
    debs: tuple[str, ...] = ()


def dpkg_name(entry: str) -> str:
    """The dpkg package of an entry: a pin's repo basename, any other entry unchanged."""
    return entry.rsplit("/", 1)[-1] if entry.startswith(PIN_PREFIX) else entry


def _is_deb_entry(name: str) -> bool:
    return name in DPKG_BACKED_CUSTOM or name.startswith(PIN_PREFIX)


def split_removals(pending: Sequence[str]) -> Split:
    return Split(
        apt=tuple(n for n in pending if is_apt_package(n)),
        flatpak=tuple(n.removeprefix(flatpak.PREFIX) for n in pending if flatpak.is_flatpak_entry(n)),
        manual=tuple(n for n in pending if n in CUSTOM_INSTALL_PACKAGES - DPKG_BACKED_CUSTOM),
        debs=tuple(n for n in pending if _is_deb_entry(n)),
    )


def dpkg_names(entries: Iterable[str]) -> frozenset[str]:
    """The dpkg packages that the apt, `.deb`-backed custom and pin entries among `entries` install."""
    split = split_removals(tuple(entries))
    return frozenset({*split.apt, *(dpkg_name(entry) for entry in split.debs)})


def moved_entries(candidates: Iterable[str], wanted: Iterable[str]) -> tuple[str, ...]:
    """The candidates whose dpkg package a wanted entry still installs."""
    covered = dpkg_names(wanted)
    return tuple(entry for entry in sorted(candidates) if dpkg_names((entry,)) & covered)


def entries_for(split: Split, removed: Sequence[str]) -> list[str]:
    """Maps removed dpkg names back to the entries that named them."""
    by_dpkg = {dpkg_name(entry): entry for entry in split.debs}
    return [by_dpkg.get(name, name) for name in removed]


def _installed_apt(t: Tooling) -> set[str]:
    listing = t.run(["dpkg-query", "-W", STATUS_FORMAT], capture_output=True, text=True).stdout or ""
    return {line.split()[1] for line in listing.splitlines() if line.startswith("ii ") and len(line.split()) > 1}


def _flatpak_installed(t: Tooling, app_id: str) -> bool:
    return t.run(["flatpak", "info", "--user", app_id], capture_output=True).returncode == 0


def installed_only(t: Tooling, split: Split) -> Split:
    present = _installed_apt(t) if split.apt or split.debs else set()
    debs = tuple(e for e in split.debs if dpkg_name(e) in present)
    return Split(
        apt=(*(n for n in split.apt if n in present), *(dpkg_name(e) for e in debs)),
        flatpak=tuple(i for i in split.flatpak if _flatpak_installed(t, i)),
        manual=split.manual,
        debs=debs,
    )


def _would_remove(ctx: SystemContext, name: str) -> Result[frozenset[str]]:
    """The packages the simulation removes, or why the simulation cannot vouch for removing `name`."""
    result = ctx.t.run(["apt-get", "-s", "remove", "-y", name], capture_output=True, text=True)
    if result.returncode != 0:
        return Err(f"exit {result.returncode}: {(result.stderr or '').strip()}")
    lines = (result.stdout or "").splitlines()
    listed = frozenset(line.split()[1] for line in lines if line.startswith("Remv ") and len(line.split()) > 1)
    return Ok(listed) if name in listed else Err(f"it does not list {name}")


def _remove_one_apt(ctx: SystemContext, name: str, undo_action: str) -> bool:
    match _would_remove(ctx, name):
        case Err(error=reason):
            ctx.t.logger.warn(f"Skipping {name}: apt simulation failed ({reason}).")
            return False
        case Ok(value=listed):
            return _remove_listed(ctx, name, listed, undo_action)


def _remove_listed(ctx: SystemContext, name: str, listed: frozenset[str], undo_action: str) -> bool:
    extras = listed - {name}
    if extras:
        ctx.t.logger.warn(f"Skipping {name}: removing it would also remove {', '.join(sorted(extras))}.")
        return False
    if not ctx.quiet("sudo", "apt-get", "remove", "-y", name):
        ctx.t.logger.warn(f"Failed to remove {name}.")
        return False
    ctx.track(f"{undo_action}:{name}")
    return True


def remove_apt(ctx: SystemContext, names: Sequence[str], deb_names: frozenset[str] = frozenset()) -> list[str]:
    """Removes each name after a clean simulation; `deb_names` have no apt source, so their undo is manual."""
    return [name for name in names if _remove_one_apt(ctx, name, "DEB_REMOVED" if name in deb_names else "APT_REMOVED")]


def _remove_one_flatpak(t: Tooling, changes: RollbackLog, app_id: str) -> bool:
    argv = ["flatpak", "uninstall", "--user", "-y", "--noninteractive", app_id]
    if t.logger.quiet_run(argv, run=t.run).returncode != 0:
        t.logger.warn(f"Failed to remove Flatpak app {app_id}.")
        return False
    changes.track(f"FLATPAK_REMOVED:{app_id}", dry_run=t.logger.dry_run)
    return True


def remove_flatpaks(t: Tooling, changes: RollbackLog, ids: Sequence[str]) -> list[str]:
    return [app_id for app_id in ids if _remove_one_flatpak(t, changes, app_id)]
