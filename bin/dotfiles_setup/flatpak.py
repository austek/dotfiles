"""User-level Flatpak apps: package entries written as `flatpak:<app-id>`, installed from Flathub without sudo."""
from __future__ import annotations

import shutil
from collections.abc import Collection

from dotfiles_setup.tooling import Tooling, dry_run_all

PREFIX = "flatpak:"
FLATHUB_REPO = "https://dl.flathub.org/repo/flathub.flatpakrepo"


def is_flatpak_entry(name: str) -> bool:
    return name.startswith(PREFIX)


def app_ids(package_names: Collection[str]) -> list[str]:
    return sorted(name.removeprefix(PREFIX) for name in package_names if is_flatpak_entry(name))


def _installed(t: Tooling, app_id: str) -> bool:
    return t.run(["flatpak", "info", "--user", app_id], capture_output=True).returncode == 0


def _flatpak(t: Tooling, *argv: str) -> bool:
    return t.logger.quiet_run(["flatpak", *argv], run=t.run).returncode == 0


def _install_missing(t: Tooling, ids: list[str]) -> None:
    for app_id in ids:
        if _installed(t, app_id):
            t.logger.info(f"{app_id} is already installed. Skipping.")
        elif _flatpak(t, "install", "--user", "-y", "--noninteractive", "flathub", app_id):
            t.logger.success(f"{app_id} installed.")
        else:
            t.logger.error(f"Failed to install {app_id} from Flathub.")


def install_flatpaks(t: Tooling, package_names: Collection[str], upgrade: bool = False) -> bool:
    ids = app_ids(package_names)
    if not ids:
        return True
    t.logger.step("Installing Flatpak apps...")
    if dry_run_all(t, f"Would install Flatpak apps: {' '.join(ids)}", *(["Would update Flatpak apps"] if upgrade else [])):
        return True
    if shutil.which("flatpak") is None:
        t.logger.warn("flatpak is not installed; skipping Flatpak apps. Add 'flatpak' to the preset's apt list.")
        return True
    if not _flatpak(t, "remote-add", "--user", "--if-not-exists", "flathub", FLATHUB_REPO):
        t.logger.warn("Could not add the Flathub remote; skipping Flatpak apps.")
        return True
    _install_missing(t, ids)
    if upgrade and not _flatpak(t, "update", "--user", "-y", "--noninteractive"):
        t.logger.warn("flatpak update failed.")
    return True
