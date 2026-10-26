"""The apt package install and the .deb files listed in packages/github_bins.txt."""
from __future__ import annotations

import re
import tempfile
from pathlib import Path

from dotfiles_setup.release_installers import Resolved, download_with_cache
from dotfiles_setup.system_steps import SystemContext
from dotfiles_setup.tooling import dry_run_all

# Package names installed outside apt; the apt install skips them.
CUSTOM_INSTALL_PACKAGES = frozenset({
    "oh-my-zsh", "sdkman", "nvm", "lazydocker", "zoom", "istioctl", "awscli", "slack-desktop", "jetbrains-toolbox",
    "antigravity-ide", "zizmor", "mcp-grafana", "ruff", "coderabbit", "auditr", "sonarqube-cli", "uv", "cargo-deny",
    "cargo-audit",
})


def _remove_superseded_lists(ctx: SystemContext, sources_dir: Path) -> None:
    """Some packages drop a legacy .list next to a stow-managed .sources of the same name."""
    for sources in sorted(sources_dir.glob("*.sources")):
        legacy = sources.with_suffix(".list")
        if legacy.is_file():
            ctx.t.logger.info(f"Removing duplicate apt source: {legacy.name} (superseded by {sources.name})")
            ctx.t.run(["sudo", "rm", "-f", str(legacy)])


def install_packages(ctx: SystemContext, sources_dir: Path = Path("/etc/apt/sources.list.d")) -> bool:
    logger = ctx.t.logger
    logger.step("Step 4: Installing packages...")
    apt_packages = sorted(p for p in ctx.packages if p not in CUSTOM_INSTALL_PACKAGES)
    if not apt_packages:
        logger.warn("No apt packages to install.")
        return True
    if dry_run_all(ctx.t, "Would update package lists",
                   f"Would install {len(apt_packages)} apt packages: {' '.join(apt_packages)}"):
        return True
    logger.info("Updating package lists...")
    if not ctx.quiet("sudo", "apt-get", "update"):
        return False
    logger.info(f"Installing {len(apt_packages)} apt packages...")
    if not ctx.quiet("sudo", "DEBIAN_FRONTEND=noninteractive", "apt-get", "install", "-y", *apt_packages):
        return False
    logger.success("All apt packages installed.")
    _remove_superseded_lists(ctx, sources_dir)
    return True


def _bin_entries(listing: Path) -> list[tuple[str, str, str, str]]:
    """Returns (line, repo, version, filename) for each non-comment line; missing fields come back empty."""
    entries = []
    for line in listing.read_text().splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        fields = (line.split() + ["", "", ""])[:3]
        entries.append((line, *fields))
    return entries


def _already_installed(ctx: SystemContext, filename: str) -> bool:
    package = filename.split("_", 1)[0]
    listing = ctx.t.run(["dpkg", "-l"], capture_output=True, text=True).stdout or ""
    return re.search(rf"^ii  {re.escape(package)}[: ]", listing, re.MULTILINE) is not None


def _install_deb(ctx: SystemContext, repo: str, version: str, filename: str, temp_dir: Path) -> None:
    logger = ctx.t.logger
    url = f"https://github.com/{repo}/releases/download/v{version}/{filename}"
    deb = temp_dir / filename
    logger.info(f"Fetching {filename} v{version} from {repo}...")
    try:
        hit = download_with_cache(ctx.t, f"github-bins/{repo}", Resolved(version, url, f"{version}-{filename}"), deb)
    except (OSError, ValueError):
        logger.error(f"Failed to download {filename} from {url}")
        return
    if hit:
        logger.info("(using cached .deb)")
    logger.info(f"Installing {filename}...")
    if ctx.quiet("sudo", "dpkg", "-i", str(deb)):
        logger.success(f"Successfully installed {filename}.")
    else:
        logger.error(f"Failed to install {filename}. Running 'apt --fix-broken install'...")
        ctx.quiet("sudo", "apt-get", "-y", "--fix-broken", "install")


def install_github_bins(ctx: SystemContext) -> None:
    logger = ctx.t.logger
    logger.step("Step 5: Installing .deb packages from GitHub...")
    listing = ctx.dotfiles_dir / "packages" / "github_bins.txt"
    if not listing.is_file() or listing.stat().st_size == 0:
        logger.warn("github_bins.txt not found or is empty. Skipping.")
        return
    entries = _bin_entries(listing)
    if logger.dry_run:
        for _, repo, version, filename in entries:
            if repo and version and filename:
                logger.dry_run_notice(f"Would download and install {filename} from {repo} v{version}")
        return
    with tempfile.TemporaryDirectory() as temp_dir:
        for line, repo, version, filename in entries:
            if not (repo and version and filename):
                logger.error(f"Invalid line in github_bins.txt: '{line}'")
            elif _already_installed(ctx, filename):
                logger.info(f"Package {filename.split('_', 1)[0]} is already installed. Skipping.")
            else:
                _install_deb(ctx, repo, version, filename, Path(temp_dir))
