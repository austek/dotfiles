"""Clones the optional private overlay (see overlay.py)."""
from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class CloneResult:
    succeeded: bool
    returncode: int
    stdout: str


def clone_overlay(repo: str, dest: Path, *, run=subprocess.run) -> CloneResult:
    if dest.exists() or dest.is_symlink():
        return CloneResult(
            succeeded=False,
            returncode=1,
            stdout=(
                f"{dest} already exists — refusing to overwrite it. "
                f"If it's already your private overlay clone, update it with "
                f"`git -C {dest} pull` instead."
            ),
        )
    result = run(["git", "clone", repo, str(dest)], capture_output=True, text=True)
    return CloneResult(
        succeeded=result.returncode == 0,
        returncode=result.returncode,
        stdout=(result.stdout or "") + (result.stderr or ""),
    )
