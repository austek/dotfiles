"""Debian/Ubuntu backend: resolves logical package names against a preset's
overrides and hands the final list to bin/setup.sh, which still owns the
actual apt/dpkg execution (this project resolves, it doesn't re-implement
install mechanics already covered by bin/lib/apt.sh)."""
from __future__ import annotations

import shutil
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dotfiles_setup.backends import InstallResult


def setup_argv(
    dotfiles_dir: Path, package_file: Path, *, preset_name: str, claude_profile_dir: Path,
    dry_run: bool, private_root: Path | None, verbosity: int, force_stow: bool,
) -> list[str]:
    argv = [
        "bash", str(dotfiles_dir / "bin" / "setup.sh"),
        "--preset", preset_name,
        "--package-file", str(package_file),
        "--claude-profile-dir", str(claude_profile_dir),
        "--verbosity", str(verbosity),
        "--no-banner",
        "--no-header",
    ]
    argv += ["--private-root", str(private_root)] if private_root is not None else []
    argv += ["--force-stow"] if force_stow else []
    argv += ["--dry-run"] if dry_run else []
    return argv


@dataclass(frozen=True)
class AptBackend:
    dotfiles_dir: Path
    backend_overrides: dict[str, str]
    name: str = "apt"

    def detect(self) -> bool:
        return shutil.which("apt-get") is not None

    def resolve_name(self, logical_name: str) -> str:
        return self.backend_overrides.get(logical_name, logical_name)

    def install(
        self,
        package_file: Path,
        *,
        preset_name: str,
        claude_profile_dir: Path,
        dry_run: bool,
        private_root: Path | None = None,
        verbosity: int = 0,
        force_stow: bool = False,
        run: Callable[..., Any] = subprocess.run,
    ) -> InstallResult:
        argv = setup_argv(
            self.dotfiles_dir, package_file, preset_name=preset_name, claude_profile_dir=claude_profile_dir,
            dry_run=dry_run, private_root=private_root, verbosity=verbosity, force_stow=force_stow,
        )
        # Output is deliberately uncaptured so a long install streams live.
        result = run(argv)
        return InstallResult(
            succeeded=result.returncode == 0,
            returncode=result.returncode,
            stdout=(result.stdout or "") + (result.stderr or ""),
        )

    def print_completion(self, *, dry_run: bool, run: Callable[..., Any] = subprocess.run) -> None:
        sys.stdout.flush()
        argv = ["bash", str(self.dotfiles_dir / "bin" / "setup.sh"), "--banner-only"]
        run(argv + (["--dry-run"] if dry_run else []))
