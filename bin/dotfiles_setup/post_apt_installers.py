"""Installers that need pipx or cargo from the apt step; a failure logs an error and continues."""
from __future__ import annotations

import os
import re
import shutil

from dotfiles_setup.tooling import Installer, Tooling, dry_run_all
from dotfiles_setup.vendor_installers import install_ruff, run_vendor_script

AUDITR_VERSION = "0.10.5"
CARGO_MIN_MINOR = 88
RUSTUP_INIT_URL = "https://sh.rustup.rs"


def _auditr_working(t: Tooling) -> bool:
    return t.run(["auditr", "version"], capture_output=True).returncode == 0


def _inject_packaging(t: Tooling) -> None:
    if t.run(["pipx", "inject", "--quiet", "auditr", "packaging"]).returncode != 0:
        t.logger.error("Failed to inject packaging into auditr. Run manually: pipx inject auditr packaging")
    elif _auditr_working(t):
        t.logger.success("auditr runtime dependency (packaging) injected.")
    else:
        t.logger.error("auditr still fails to start after injecting packaging. Diagnose with: auditr version")


def _python_is_recent(t: Tooling) -> bool:
    check = "import sys; sys.exit(sys.version_info < (3, 13))"
    return t.run(["python3", "-c", check], capture_output=True).returncode == 0


def _repair_or_skip_auditr(t: Tooling) -> None:
    if not t.logger.dry_run and shutil.which("pipx") is not None and not _auditr_working(t):
        t.logger.info("auditr is installed but broken; repairing.")
        _inject_packaging(t)
        return
    t.logger.info("auditr is already installed. Skipping.")


def _pipx_install_auditr(t: Tooling) -> None:
    pin = f"auditr=={AUDITR_VERSION}"
    if shutil.which("pipx") is None:
        t.logger.error(f"pipx not found; can't install auditr. Add 'pipx' to packages/apt_common.txt and re-run, or install manually: pipx install {pin}")
    elif not _python_is_recent(t):
        t.logger.error(f"auditr needs Python >= 3.13 and python3 here is older. Install manually: pipx install --python python3.13 {pin}")
    elif t.run(["pipx", "install", "--quiet", "--python", "python3", pin]).returncode != 0:
        t.logger.error(f"Failed to install auditr via pipx. Install it manually: pipx install {pin}")
    else:
        t.logger.success(f"auditr {AUDITR_VERSION} installed successfully.")
        _inject_packaging(t)


def install_auditr(t: Tooling) -> None:
    t.logger.info("Installing auditr...")
    if shutil.which("auditr") is not None:
        _repair_or_skip_auditr(t)
    elif not dry_run_all(t, f"Would install auditr=={AUDITR_VERSION} via pipx."):
        _pipx_install_auditr(t)


def _cargo_minor(t: Tooling, cargo: str) -> int:
    env = {**os.environ, "RUSTUP_TOOLCHAIN": "stable"}
    try:
        result = t.run([cargo, "--version"], capture_output=True, text=True, env=env)
    except OSError:
        return 0
    match = re.match(r"cargo 1\.(\d+)", result.stdout or "")
    return int(match.group(1)) if match else 0


def _cargo_meets_min(t: Tooling, cargo: str) -> bool:
    return _cargo_minor(t, cargo) >= CARGO_MIN_MINOR


def _install_rustup_toolchain(t: Tooling) -> bool:
    rustup = t.home / ".cargo/bin/rustup"
    t.logger.info(f"No cargo >= 1.{CARGO_MIN_MINOR} found; installing a minimal rustup toolchain...")
    if rustup.is_file() and os.access(rustup, os.X_OK):
        return t.run([str(rustup), "update", "stable", "--no-self-update"]).returncode == 0
    return run_vendor_script(t, RUSTUP_INIT_URL, "sh", "-y", "--profile", "minimal", "--no-modify-path")


def _cargo_for_crates(t: Tooling) -> str | None:
    """Returns a cargo meeting CARGO_MIN_MINOR, installing a rustup toolchain if needed; None if unavailable."""
    if _cargo_meets_min(t, "cargo"):
        return shutil.which("cargo")
    rustup_cargo = str(t.home / ".cargo/bin/cargo")
    if not _cargo_meets_min(t, rustup_cargo) and not _install_rustup_toolchain(t):
        return None
    return rustup_cargo if _cargo_meets_min(t, rustup_cargo) else None


def _run_cargo(t: Tooling, cargo: str, *args: str) -> bool:
    rustup_bin = t.home / ".cargo/bin"
    env = None
    if cargo == str(rustup_bin / "cargo"):
        # Pins the rustup proxy and its rustc to stable, whatever the user's default toolchain is.
        env = {**os.environ, "RUSTUP_TOOLCHAIN": "stable", "PATH": f"{rustup_bin}:{os.environ.get('PATH', '')}"}
    return t.run([cargo, *args], env=env).returncode == 0


def _crate_present(t: Tooling, crate: str) -> bool:
    local_bin = t.home / ".local/bin" / crate
    return shutil.which(crate) is not None or (local_bin.is_file() and os.access(local_bin, os.X_OK))


def install_cargo_crate(t: Tooling, crate: str) -> None:
    t.logger.info(f"Installing {crate}...")
    manual = f"cargo install --locked --root ~/.local {crate}"
    if _crate_present(t, crate):
        t.logger.info(f"{crate} is already installed. Skipping.")
    elif dry_run_all(t, f"Would install {crate} via cargo install."):
        return
    elif shutil.which("cargo") is None:
        t.logger.error(f"cargo not found; can't install {crate}. Add 'cargo' to the preset's package list and re-run, or install manually: {manual}")
    elif (cargo := _cargo_for_crates(t)) is None:
        t.logger.error(f"No cargo >= 1.{CARGO_MIN_MINOR} available for {crate}. Install rustup (https://rustup.rs) and re-run, or run: {manual}")
    elif _run_cargo(t, cargo, "install", "--locked", "--quiet", "--root", str(t.home / ".local"), crate):
        t.logger.success(f"{crate} installed successfully.")
    else:
        t.logger.error(f"Failed to install {crate}. Install it manually: {manual}")


POST_APT_INSTALLERS: tuple[tuple[str, Installer], ...] = (
    ("ruff", install_ruff),
    ("auditr", install_auditr),
    ("cargo-deny", lambda t: install_cargo_crate(t, "cargo-deny")),
    ("cargo-audit", lambda t: install_cargo_crate(t, "cargo-audit")),
)
