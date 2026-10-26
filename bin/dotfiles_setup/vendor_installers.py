"""Installers that hand off to a vendor's own install script (CodeRabbit CLI,
SonarQube CLI, uv) or to pipx (ruff). A failure logs an error and never aborts setup."""
from __future__ import annotations

import os
import shutil
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from dotfiles_setup.tooling import Installer, Tooling, dry_run_all


def run_vendor_script(t: Tooling, url: str, shell: str, *args: str) -> bool:
    """Downloads the script in full before executing it, so a truncated transfer never runs."""
    with tempfile.TemporaryDirectory() as temp_dir:
        script = Path(temp_dir) / "install"
        try:
            t.download(url, script)
        except (OSError, ValueError) as error:
            t.logger.error(f"Could not download {url}: {error}")
            return False
        return t.run([shell, str(script), *args]).returncode == 0


@dataclass(frozen=True)
class VendorSpec:
    name: str
    is_installed: Callable[[Tooling], bool]
    url: str
    shell: str
    dry_run_message: str
    success: Callable[[Tooling], str]


def install_vendor(t: Tooling, spec: VendorSpec) -> None:
    t.logger.info(f"Installing {spec.name}...")
    if spec.is_installed(t):
        t.logger.info(f"{spec.name} is already installed. Skipping.")
        return
    if dry_run_all(t, spec.dry_run_message):
        return
    if run_vendor_script(t, spec.url, spec.shell):
        t.logger.success(spec.success(t))
    else:
        t.logger.error(
            f"Failed to install {spec.name}. Install it manually: "
            f"curl -fsSL -o install.sh {spec.url} && {spec.shell} install.sh"
        )


def _on_path_or_at(binary: str, fallback: Callable[[Path], Path]) -> Callable[[Tooling], bool]:
    def check(t: Tooling) -> bool:
        path = fallback(t.home)
        return shutil.which(binary) is not None or (path.is_file() and os.access(path, os.X_OK))

    return check


def _coderabbit_success(t: Tooling) -> str:
    binary = shutil.which("coderabbit")
    if binary is None:
        return "CodeRabbit CLI installed (restart your shell to put it on PATH)."
    result = t.run([binary, "--version"], capture_output=True, text=True)
    return f"CodeRabbit CLI installed ({(result.stdout or '').strip()})."


CODERABBIT = VendorSpec(
    "CodeRabbit CLI", lambda t: shutil.which("coderabbit") is not None,
    "https://cli.coderabbit.ai/install.sh", "sh",
    "Would install the CodeRabbit CLI via https://cli.coderabbit.ai's install script.",
    _coderabbit_success,
)
SONARQUBE_CLI = VendorSpec(
    "SonarQube CLI", _on_path_or_at("sonar", lambda home: home / ".local/share/sonarqube-cli/bin/sonar"),
    "https://raw.githubusercontent.com/SonarSource/sonarqube-cli/refs/heads/master/user-scripts/install.sh", "bash",
    "Would install the SonarQube CLI via SonarSource's install script.",
    lambda t: "SonarQube CLI installed.",
)
UV = VendorSpec(
    "uv", _on_path_or_at("uv", lambda home: home / ".local/bin/uv"),
    "https://astral.sh/uv/install.sh", "sh",
    "Would install uv via https://astral.sh/uv/install.sh.",
    lambda t: "uv installed.",
)


def install_ruff(t: Tooling) -> None:
    t.logger.info("Installing ruff...")
    if shutil.which("ruff") is not None:
        t.logger.info("ruff is already installed. Skipping.")
        return
    if dry_run_all(t, "Would install ruff via pipx."):
        return
    if shutil.which("pipx") is None:
        t.logger.error(
            "pipx not found; can't install ruff. Add 'pipx' to packages/apt_common.txt and re-run, "
            "or install manually: pipx install ruff"
        )
    elif t.run(["pipx", "install", "--quiet", "ruff"]).returncode == 0:
        t.logger.success("ruff installed successfully.")
    else:
        t.logger.error("Failed to install ruff via pipx. Install it manually: pipx install ruff")


VENDOR_INSTALLERS: tuple[tuple[str, Installer], ...] = (
    ("coderabbit", lambda t: install_vendor(t, CODERABBIT)),
    ("sonarqube-cli", lambda t: install_vendor(t, SONARQUBE_CLI)),
    ("uv", lambda t: install_vendor(t, UV)),
)
