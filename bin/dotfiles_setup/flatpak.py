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


def _install_one(t: Tooling, app_id: str) -> bool:
    if _installed(t, app_id):
        t.logger.info(f"{app_id} is already installed. Skipping.")
        return True
    if _flatpak(t, "install", "--user", "-y", "--noninteractive", "flathub", app_id):
        t.logger.success(f"{app_id} installed.")
        return True
    t.logger.error(f"Failed to install {app_id} from Flathub.")
    return False


def _install_missing(t: Tooling, ids: list[str]) -> tuple[str, ...]:
    return tuple(app_id for app_id in ids if not _install_one(t, app_id))


def _ready(t: Tooling, ids: list[str]) -> bool:
    if shutil.which("flatpak") is None:
        report = t.logger.error if ids else t.logger.info
        report("flatpak is not installed; skipping Flatpak apps. Add 'flatpak' to the preset's apt list.")
        return False
    if ids and not _flatpak(t, "remote-add", "--user", "--if-not-exists", "flathub", FLATHUB_REPO):
        t.logger.error("Could not add the Flathub remote; skipping Flatpak apps.")
        return False
    return True


def install_flatpaks(t: Tooling, package_names: Collection[str], upgrade: bool = False) -> tuple[str, ...]:
    """Installs the listed apps and, on upgrade, updates every Flatpak app. Returns the app ids that failed to install, all of them when Flatpak is unusable. Failures are logged and never stop the install."""
    ids = app_ids(package_names)
    if not ids and not upgrade:
        return ()
    t.logger.step("Installing Flatpak apps...")
    notices = ([f"Would install Flatpak apps: {' '.join(ids)}"] if ids else []) + (["Would update Flatpak apps"] if upgrade else [])
    if dry_run_all(t, *notices):
        return ()
    if not _ready(t, ids):
        return tuple(ids)
    failed = _install_missing(t, ids)
    if upgrade and not _flatpak(t, "update", "--user", "-y", "--noninteractive"):
        t.logger.error("flatpak update failed.")
    return failed
