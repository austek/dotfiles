"""Keeps a machine's hand-edited package list in sync with its preset without
clobbering edits: new entries the preset gained get appended; entries the
user removed from the forked file are never re-added, regardless of what
else about the preset changes at the same time."""
from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from dotfiles_setup.presets import package_names


def names_to_append(
    resolved_names: Sequence[str], previous_names: Sequence[str] | None, existing: set[str]
) -> list[str]:
    # A name the preset already carried that the user deleted must never come back.
    return sorted(set(resolved_names) - set(previous_names or ()) - existing)


def effective_names(
    package_file: Path, resolved_names: Sequence[str], previous_names: Sequence[str] | None
) -> frozenset[str]:
    if not package_file.is_file():
        return frozenset(resolved_names)
    existing = package_names(package_file.read_text())
    return frozenset(existing | set(names_to_append(resolved_names, previous_names, existing)))


def _append(package_file: Path, names: list[str]) -> None:
    with package_file.open("a") as handle:
        handle.write("\n# --- added by reconcile ---\n")
        handle.writelines(f"{name}\n" for name in names)


def reconcile_package_file(
    package_file: Path, resolved_names: Sequence[str], previous_names: Sequence[str] | None
) -> tuple[list[str], bool]:
    if not package_file.is_file():
        package_file.parent.mkdir(parents=True, exist_ok=True)
        sorted_names = sorted(set(resolved_names))
        package_file.write_text("\n".join(sorted_names) + "\n")
        return (sorted_names, True)
    newly_added = names_to_append(resolved_names, previous_names, package_names(package_file.read_text()))
    if not newly_added:
        return ([], False)
    _append(package_file, newly_added)
    return (newly_added, True)
