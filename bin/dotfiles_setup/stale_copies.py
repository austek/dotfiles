"""Reports a same-named copy in `~/.dotfiles/bin`, `~/bin` or `/usr/local/bin` of each binary dfctl manages in `~/.local/bin`; never removes one."""
from __future__ import annotations

import os
from collections.abc import Collection, Iterable, Iterator
from pathlib import Path

from dotfiles_setup import release_installers
from dotfiles_setup.release_installers import USER_BINARY_SPECS, user_bin_dir
from dotfiles_setup.tooling import Tooling
from dotfiles_setup.user_links import USER_LINKS

VENDOR_PACKAGES = frozenset({"uv", "ruff", "auditr", "cargo-deny", "cargo-audit", "coderabbit"})
ALWAYS_MANAGED = frozenset({"rtk"})


def search_dirs(t: Tooling) -> tuple[Path, ...]:
    """The three directories that can hold a copy plus the managed one, in PATH order: `zsh/.zshenv` orders the first three, and `/usr/local/bin` comes from the inherited PATH."""
    return (t.home / ".dotfiles" / "bin", t.home / "bin", user_bin_dir(t), release_installers.SYSTEM_BIN_DIR)


def managed_names(package_names: Collection[str]) -> set[str]:
    """Binary names of the wanted packages that dfctl places in `~/.local/bin`, plus the tools every run installs."""
    binaries = {spec.binary for package, spec in USER_BINARY_SPECS if package in package_names and spec.binary}
    links = {name for package, name, _ in USER_LINKS if package in package_names}
    return binaries | links | (VENDOR_PACKAGES & set(package_names)) | ALWAYS_MANAGED


def _is_other_file(copy: Path, managed: Path) -> bool:
    return copy.is_file() and not copy.samefile(managed)


def _message(copy: Path, managed: Path, on_path: bool) -> str:
    if not on_path:
        return f"{copy} also exists; it is not on PATH here."
    return f"{copy} is now shadowed by {managed}; remove it with sudo when convenient."


def _on_path(directory: Path) -> bool:
    entries = (os.path.normpath(entry) for entry in os.environ.get("PATH", "").split(os.pathsep) if entry)
    return os.path.normpath(directory) in entries


def _copies(t: Tooling, names: Iterable[str]) -> Iterator[tuple[Path, Path, bool]]:
    dirs, managed_dir = search_dirs(t), user_bin_dir(t)
    rank = dirs.index(managed_dir)
    others = [(directory, position < rank) for position, directory in enumerate(dirs) if directory != managed_dir]
    for name in sorted(names):
        managed = managed_dir / name
        if not release_installers.is_executable(managed):
            continue
        for directory, shadows in others:
            if _is_other_file(directory / name, managed):
                yield directory / name, managed, shadows


def shadowing_copies(t: Tooling, names: Iterable[str]) -> tuple[tuple[Path, Path], ...]:
    """Pairs of (copy, managed binary) where the copy precedes `~/.local/bin` on `PATH`."""
    return tuple(
        (copy, managed) for copy, managed, shadows in _copies(t, names)
        if shadows and release_installers.is_executable(copy)
    )


def report_stale_copies(t: Tooling, names: Iterable[str]) -> None:
    """Logs one line per copy that comes after `~/.local/bin` on `PATH`, saying whether its directory is on `PATH`; copies ahead of it are `shadowing_copies`."""
    for copy, managed, shadows in _copies(t, names):
        if not shadows:
            t.logger.info(_message(copy, managed, _on_path(copy.parent)))
