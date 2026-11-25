"""Installs the CLIs Claude Code's hooks and MCP servers need; failures log an error and continue."""
from __future__ import annotations

import os
import re
import shutil
import sys
from pathlib import Path

from dotfiles_setup.release_installers import user_bin_dir
from dotfiles_setup.tooling import Tooling, dry_run_all
from dotfiles_setup.vendor_installers import run_vendor_script

RTK_INSTALL_URL = "https://raw.githubusercontent.com/rtk-ai/rtk/refs/heads/master/install.sh"
CAVEMAN_INSTALL = ["npm", "install", "-g", "--ignore-scripts", "@caveman-ai/cli"]


def _tool_env(binary: str) -> dict[str, str] | None:
    """Stops cozempic's first-run init from writing its hooks into the generated settings.json."""
    if Path(binary).name != "cozempic":
        return None
    return {**os.environ, "COZEMPIC_NO_GLOBAL_INIT": "1"}


def _version_of(t: Tooling, binary: str, first_line: bool = False) -> str:
    try:
        out = (t.run([binary, "--version"], capture_output=True, text=True, env=_tool_env(binary)).stdout or "").strip()
    except OSError:
        return ""
    return out.splitlines()[0] if first_line and out else out


def _node_version_key(directory: Path) -> tuple[int, ...]:
    return tuple(int(part) for part in re.findall(r"\d+", directory.parent.name))


def _nvm_bin_dir(home: Path) -> Path | None:
    candidates = sorted((home / ".nvm/versions/node").glob("*/bin"), key=_node_version_key)
    return candidates[-1] if candidates else None


def _node_env(t: Tooling) -> dict[str, str]:
    """Puts the newest nvm node on PATH: the nvm installer's shell is gone by the time this runs."""
    nvm_bin = _nvm_bin_dir(t.home)
    path = os.environ.get("PATH", "")
    return {**os.environ, "PATH": f"{nvm_bin}:{path}" if nvm_bin else path}


def configure_rtk_cli(t: Tooling) -> None:
    t.logger.step("Step 7c: Verifying the rtk CLI is installed...")
    if shutil.which("rtk") is not None:
        t.logger.success(f"rtk CLI already installed ({_version_of(t, 'rtk')}).")
    elif not dry_run_all(t, "Would install the rtk CLI via https://github.com/rtk-ai/rtk's install script."):
        t.logger.info("rtk CLI not found; installing...")
        if run_vendor_script(t, RTK_INSTALL_URL, "sh"):
            binary = shutil.which("rtk")
            t.logger.success(f"rtk CLI installed ({_version_of(t, binary) if binary else ''}).")
        else:
            t.logger.error(f"Failed to install rtk. Install it manually: curl -fsSL {RTK_INSTALL_URL} | sh")


def configure_cozempic_cli(t: Tooling) -> None:
    t.logger.step("Step 7d: Verifying the cozempic CLI is installed...")
    if shutil.which("cozempic") is not None:
        t.logger.success(f"cozempic CLI already installed ({_version_of(t, 'cozempic')}).")
    elif dry_run_all(t, "Would install the cozempic CLI via pipx."):
        return
    elif shutil.which("pipx") is None:
        t.logger.error("pipx not found; can't install cozempic. Add 'pipx' to packages/apt_common.txt and re-run, or install manually: pipx install cozempic")
    elif t.run(["pipx", "install", "--quiet", "cozempic"]).returncode != 0:
        t.logger.error("Failed to install cozempic via pipx. Install it manually: pipx install cozempic")
    else:
        _report_cozempic(t)


def _report_cozempic(t: Tooling) -> None:
    local_bin = user_bin_dir(t)
    found = shutil.which("cozempic", path=f"{local_bin}:{os.environ.get('PATH', '')}")
    if found is None:
        t.logger.warn("cozempic installed but not found on PATH yet; it will resolve once ~/.local/bin is sourced (log out/in or restart your shell).")
    else:
        t.logger.success(f"cozempic CLI installed ({_version_of(t, found)}).")


def _caveman_version(t: Tooling, caveman: str, env: dict[str, str]) -> str:
    out = t.run([caveman, "version"], capture_output=True, text=True, env=env).stdout or ""
    match = re.search(r'"version": "([^"]*)"', out)
    return match.group(1) if match else ""


def _install_caveman_cli(t: Tooling, env: dict[str, str]) -> bool:
    if shutil.which("caveman", path=env["PATH"]) is not None:
        return True
    if dry_run_all(t, "Would install the caveman CLI via: npm install -g --ignore-scripts @caveman-ai/cli"):
        return False
    t.logger.info("caveman CLI not found; installing...")
    if t.run(CAVEMAN_INSTALL, env=env).returncode != 0:
        t.logger.error("Failed to install @caveman-ai/cli via npm. Install it manually: npm install -g --ignore-scripts @caveman-ai/cli")
        return False
    t.logger.success("caveman CLI installed.")
    return True


def _install_caveman_engine(t: Tooling, caveman: str, env: dict[str, str]) -> None:
    status = t.run([caveman, "status"], capture_output=True, text=True, env=env).stdout or ""
    if "caveman-proxy not installed" not in status:
        t.logger.success("caveman proxy engine already installed.")
    elif not dry_run_all(t, "Would install the caveman proxy engine via: caveman setup --install"):
        t.logger.info("caveman proxy engine not found; installing...")
        result = t.run([caveman, "setup", "--install"], capture_output=True, text=True, env=env)
        if result.returncode == 0:
            t.logger.success("caveman proxy engine installed.")
        else:
            print((result.stdout or "") + (result.stderr or ""), file=sys.stderr, end="")
            t.logger.error("Failed to install the caveman proxy engine. Run manually: caveman setup --install")


def configure_caveman_proxy(t: Tooling) -> None:
    """Installs the CLI and engine only: `caveman enable claude` would clobber settings.json's hand-tuned hooks."""
    t.logger.step("Step 7f: Verifying the caveman proxy CLI is installed...")
    env = _node_env(t)
    if shutil.which("npm", path=env["PATH"]) is None:
        t.logger.warn("npm not found; skipping caveman proxy setup.")
        return
    if shutil.which("caveman", path=env["PATH"]) is not None:
        t.logger.success(f"caveman CLI already installed ({_caveman_version(t, 'caveman', env)}).")
    if not _install_caveman_cli(t, env):
        return
    caveman = shutil.which("caveman", path=env["PATH"])
    if caveman is not None:
        _install_caveman_engine(t, caveman, env)


def configure_claude_tools(t: Tooling) -> None:
    configure_rtk_cli(t)
    configure_cozempic_cli(t)
    configure_caveman_proxy(t)
