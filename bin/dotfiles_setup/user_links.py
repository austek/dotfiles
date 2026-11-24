"""Symlinks tools that install under their own directory into `~/.local/bin`, so one PATH entry finds them."""
from __future__ import annotations

from collections.abc import Callable, Collection
from pathlib import Path

from dotfiles_setup.fsutil import link_executable
from dotfiles_setup.release_installers import ensure_user_bin_dir, user_bin_dir
from dotfiles_setup.result import Err
from dotfiles_setup.rollback import RollbackLog
from dotfiles_setup.tooling import Tooling, dry_run_all

USER_LINKS: tuple[tuple[str, str, Callable[[Path], Path]], ...] = (
    ("jetbrains-toolbox", "jetbrains-toolbox", lambda home: home / ".local/share/JetBrains/Toolbox/bin/jetbrains-toolbox"),
    ("sonarqube-cli", "sonar", lambda home: home / ".local/share/sonarqube-cli/bin/sonar"),
)


CONSEQUENCES = {
    "sonar": "`sonar` on PATH is not the SonarQube CLI",
    "jetbrains-toolbox": "`jetbrains-toolbox` on PATH is not the Toolbox launcher",
}


def _warn_unlinked(t: Tooling, name: str, reason: str) -> None:
    t.logger.warn(f"{reason} Until it is fixed, {CONSEQUENCES[name]}.")


def _already_linked(real: Path, link: Path) -> bool:
    return link.is_symlink() and link.resolve() == real.resolve()


def pending(t: Tooling, package_names: Collection[str]) -> tuple[str, ...]:
    """The links `link_user_tools` would create or replace: wanted, installed tools whose link is missing or a stale symlink. A regular file at the link name is kept, so it is not listed."""
    links = ((user_bin_dir(t) / name, locate(t.home)) for package, name, locate in USER_LINKS if package in package_names)
    return tuple(f"link {link}" for link, real in links if real.is_file() and _needs_link(real, link))


def _needs_link(real: Path, link: Path) -> bool:
    return (link.is_symlink() or not link.exists()) and not _already_linked(real, link)


def _link_one(t: Tooling, name: str, real: Path, changes: RollbackLog | None) -> None:
    link = user_bin_dir(t) / name
    if _already_linked(real, link):
        return
    if dry_run_all(t, f"Would link {link} to {real}"):
        return
    if not ensure_user_bin_dir(t, changes):
        _warn_unlinked(t, name, f"Could not link {link}.")
        return
    fresh = not link.is_symlink() and not link.exists()
    match link_executable(real, name, link.parent):
        case Err(error=message):
            _warn_unlinked(t, name, message)
        case _:
            if fresh and changes is not None:
                changes.track(f"LINK_INSTALLED:{real.parent}|{link}", dry_run=False)
            t.logger.info(f"Linked {link} to {real}.")


def link_user_tools(t: Tooling, package_names: Collection[str], changes: RollbackLog | None = None) -> bool:
    """Links each wanted, installed tool into `~/.local/bin`; a name taken by a regular file or directory is warned about and kept. Never fails the step."""
    for package, name, locate in USER_LINKS:
        real = locate(t.home)
        if package in package_names and real.is_file():
            _link_one(t, name, real, changes)
    return True
