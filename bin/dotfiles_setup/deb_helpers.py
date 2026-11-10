"""dpkg queries and installs shared by the vendor .deb installers."""
from __future__ import annotations

import os
import re
from pathlib import Path

from dotfiles_setup.tooling import Tooling


def _dpkg_listing(t: Tooling) -> str:
    return t.run(["dpkg", "-l"], capture_output=True, text=True).stdout or ""


def _dpkg_version(t: Tooling, package: str) -> str | None:
    listing = t.run(["dpkg", "-l"], capture_output=True, text=True, env={**os.environ, "COLUMNS": "400"}).stdout or ""
    match = re.search(rf"^ii  {re.escape(package)}(?::\S+)?\s+(\S+)", listing, re.MULTILINE)
    return match.group(1) if match else None


def deb_is_current(installed: str | None, latest: str) -> bool:
    """True when the dpkg version is `latest`, ignoring an epoch prefix and a `-`/`+` revision suffix."""
    return installed is not None and re.fullmatch(rf"(\d+:)?{re.escape(latest)}([-+].*)?", installed) is not None


def _install_deb_or_fix_broken(t: Tooling, deb: Path, package: str) -> bool:
    before = _dpkg_version(t, package)
    if t.logger.quiet_run(["sudo", "dpkg", "-i", str(deb)], run=t.run).returncode == 0:
        return True
    t.logger.warn("dpkg reported errors. Running 'apt --fix-broken install'...")
    t.logger.quiet_run(["sudo", "apt-get", "-y", "--fix-broken", "install"], run=t.run)
    after = _dpkg_version(t, package)
    return after is not None and after != before


def _is_older(t: Tooling, installed: str, pinned: str) -> bool | None:
    """None when dpkg could not compare the two versions."""
    code = t.run(["dpkg", "--compare-versions", installed, "lt", pinned]).returncode
    return {0: True, 1: False}.get(code)
