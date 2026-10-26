"""Third-party installers that run between the shell apt-source and package
steps: the script-based tool managers (sdkman, oh-my-zsh, nvm) and the
release-artifact installers in release_installers.py."""
from __future__ import annotations

import json
import os
from collections.abc import Callable, Collection
from pathlib import Path

from dotfiles_setup import release_installers
from dotfiles_setup.tooling import Tooling, dry_run_all, fetch_https

__all__ = ["TOOL_INSTALLERS", "Tooling", "fetch_https", "install_tools"]

SDKMAN_URL = "https://get.sdkman.io?rcupdate=false"
OMZ_URL = "https://raw.githubusercontent.com/ohmyzsh/ohmyzsh/master/tools/install.sh"
NVM_RELEASE_API = "https://api.github.com/repos/nvm-sh/nvm/releases/latest"
NVM_FALLBACK_URL = "https://raw.githubusercontent.com/nvm-sh/nvm/v0.39.7/install.sh"
NVM_HELP_URL = "https://github.com/nvm-sh/nvm#installing-and-updating"
MSG_CONTINUING_SETUP = "Continuing with setup..."
NODE_LTS_SCRIPT = (
    'export NVM_DIR="$1"; . "$1/nvm.sh"; '
    '[ -s "$1/bash_completion" ] && . "$1/bash_completion"; '
    "nvm install --lts && nvm use --lts && nvm alias default 'lts/*'"
)


def _run_script(t: Tooling, name: str, url: str, argv: list[str], env: dict[str, str] | None = None) -> bool:
    t.logger.info(f"Downloading and running {name} install script...")
    try:
        script = t.fetch(url)
    except (OSError, ValueError) as error:
        t.logger.error(f"Could not download the {name} install script: {error}")
        return False
    result = t.run(argv, input=script, text=True, env=env)
    return result.returncode == 0


def install_sdkman(t: Tooling) -> bool:
    t.logger.info("Installing SDKMAN...")
    if (t.home / ".sdkman").is_dir():
        t.logger.info("SDKMAN is already installed. Skipping.")
        return True
    if dry_run_all(t, "Would download and install SDKMAN from https://get.sdkman.io"):
        return True
    ok = _run_script(t, "SDKMAN", SDKMAN_URL, ["bash"])
    if ok:
        t.logger.success("SDKMAN installed.")
    return ok


def install_omz(t: Tooling) -> bool:
    t.logger.info("Installing Oh My Zsh...")
    if (t.home / ".oh-my-zsh").is_dir():
        t.logger.info("Oh My Zsh is already installed. Skipping.")
        return True
    if dry_run_all(t, "Would download and install Oh My Zsh"):
        return True
    env = {**os.environ, "KEEP_ZSHRC": "yes", "RUNZSH": "no", "CHSH": "no"}
    ok = _run_script(t, "Oh My Zsh", OMZ_URL, ["sh", "-s", "--", "--unattended"], env)
    if ok:
        t.logger.success("Oh My Zsh installed.")
    return ok


def _nvm_script_url(t: Tooling) -> str:
    try:
        assets = json.loads(t.fetch(NVM_RELEASE_API)).get("assets", [])
        return next(a["browser_download_url"] for a in assets if a["browser_download_url"].endswith("install.sh"))
    except (OSError, ValueError, StopIteration, KeyError):
        t.logger.warn("Could not get NVM install script URL. Trying default.")
        t.logger.warn(f"Visit: {NVM_HELP_URL}")
        return NVM_FALLBACK_URL


def _install_node_lts(t: Tooling, nvm_dir: Path) -> None:
    if not (nvm_dir / "nvm.sh").is_file():
        t.logger.warn("NVM command not available in current shell. Node.js installation will be skipped.")
        t.logger.warn("Please restart your shell and run 'nvm install --lts' manually.")
        return
    t.logger.info("Installing latest LTS version of Node.js...")
    if t.run(["bash", "-c", NODE_LTS_SCRIPT, "bash", str(nvm_dir)]).returncode == 0:
        t.logger.success("NVM and latest LTS Node.js installed.")
        return
    t.logger.error("Failed to install Node.js LTS. Please check nvm logs.")
    t.logger.error(f"Visit: {NVM_HELP_URL}")
    t.logger.warn(MSG_CONTINUING_SETUP)


def install_nvm(t: Tooling) -> bool:
    t.logger.info("Installing nvm (Node Version Manager)...")
    nvm_dir = t.home / ".nvm"
    if nvm_dir.is_dir():
        t.logger.info("NVM directory already exists. Skipping.")
        return True
    if dry_run_all(t, "Would fetch NVM latest release from GitHub API",
                   "Would download and run NVM install script",
                   "Would install latest LTS version of Node.js"):
        return True
    if not _run_script(t, "NVM", _nvm_script_url(t), ["bash"]):
        t.logger.error(f"NVM install script failed. Visit: {NVM_HELP_URL}")
        t.logger.warn(MSG_CONTINUING_SETUP)
        return True
    _install_node_lts(t, nvm_dir)
    return True


# Order matters only for failure: a False return stops the sequence.
TOOL_INSTALLERS: tuple[tuple[str, Callable[[Tooling], bool]], ...] = (
    ("oh-my-zsh", install_omz),
    ("sdkman", install_sdkman),
    ("nvm", install_nvm),
    *release_installers.RELEASE_INSTALLERS,
)


def install_tools(t: Tooling, package_names: Collection[str]) -> bool:
    for name, installer in TOOL_INSTALLERS:
        if name in package_names and not installer(t):
            return False
    return True
