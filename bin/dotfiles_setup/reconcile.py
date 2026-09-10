"""Keeps a machine's hand-edited package list in sync with its preset without
clobbering edits: new entries the preset gained get appended; entries the
user removed from the forked file are never re-added, regardless of what
else about the preset changes at the same time."""
from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path


def _existing_names(package_file: Path) -> set[str]:
    return {
        line.strip()
        for line in package_file.read_text().splitlines()
        if line.strip() and not line.strip().startswith("#")
    }


def reconcile_package_file(
    package_file: Path, resolved_names: Sequence[str], previous_names: Sequence[str] | None
) -> tuple[list[str], bool]:
    if not package_file.is_file():
        package_file.parent.mkdir(parents=True, exist_ok=True)
        sorted_names = sorted(set(resolved_names))
        package_file.write_text("\n".join(sorted_names) + "\n")
        return (sorted_names, True)

    if previous_names is not None and set(resolved_names) == set(previous_names):
        return ([], False)

    # Only a name absent from the *previous* resolved set is genuinely new to
    # the preset — a name the preset already carried, that the user deleted
    # from the file, must never come back just because something else changed.
    newly_from_preset = set(resolved_names) - set(previous_names or ())
    newly_added = sorted(newly_from_preset - _existing_names(package_file))
    if not newly_added:
        return ([], False)

    with package_file.open("a") as handle:
        handle.write("\n# --- added by reconcile ---\n")
        for name in newly_added:
            handle.write(f"{name}\n")
    return (newly_added, True)
