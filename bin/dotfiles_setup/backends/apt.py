"""Debian/Ubuntu backend: resolves logical package names against a preset's
overrides and hands the final list to bin/setup.sh, which still owns the
actual apt/dpkg execution (this project resolves, it doesn't re-implement
install mechanics already covered by bin/lib/apt.sh)."""
from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from dotfiles_setup.backends import InstallResult


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
        run=subprocess.run,
    ) -> InstallResult:
        argv = [
            "bash", str(self.dotfiles_dir / "bin" / "setup.sh"),
            "--preset", preset_name,
            "--package-file", str(package_file),
            "--claude-profile-dir", str(claude_profile_dir),
        ]
        if private_root is not None:
            argv += ["--private-root", str(private_root)]
        if dry_run:
            argv.append("--dry-run")
        # No capture_output: setup.sh's own step-by-step logging (and -v/-vv/-vvv's extra
        # detail, and apt/stow's own output) is the only feedback during a long real
        # install — capturing it would silently swallow all of it until (if ever) a
        # failure prints it back, leaving a real run looking hung with no live output.
        result = run(argv)
        return InstallResult(
            succeeded=result.returncode == 0,
            returncode=result.returncode,
            stdout=(result.stdout or "") + (result.stderr or ""),
        )
