"""Installs the Antigravity IDE, swapping it into place only once fully staged; failures warn and continue."""
from __future__ import annotations

import platform
import re
import subprocess
import tarfile
import tempfile
from dataclasses import dataclass
from pathlib import Path

from dotfiles_setup.release_installers import Resolved, download_with_cache, skip
from dotfiles_setup.tooling import Tooling, dry_run_all

DOWNLOAD_PAGE = "https://antigravity.google/download"
PINNED_BUILD = "2.1.1-6123990880747520"
ARCH_DIRS = {"x86_64": "linux-x64", "aarch64": "linux-arm", "arm64": "linux-arm"}
CACHE_TOOL = "antigravity-ide"
DESKTOP_ENTRY = """[Desktop Entry]
Type=Application
Name=Antigravity IDE
Comment=Google Antigravity agent-first development platform
Exec={install_dir}/antigravity-ide %U
Icon=antigravity-ide
Terminal=false
Categories=Development;IDE;
StartupWMClass=Antigravity IDE
MimeType=x-scheme-handler/antigravity-ide;
"""


@dataclass(frozen=True)
class Layout:
    root: Path = Path("/")

    @property
    def install_dir(self) -> Path:
        return self.root / "opt/antigravity-ide"

    @property
    def staging_dir(self) -> Path:
        return self.install_dir.with_name("antigravity-ide.staging")

    @property
    def old_dir(self) -> Path:
        return self.install_dir.with_name("antigravity-ide.old")

    @property
    def build_file(self) -> Path:
        return self.install_dir / ".installed-build"

    @property
    def icon(self) -> Path:
        return self.root / "usr/share/icons/hicolor/512x512/apps/antigravity-ide.png"

    @property
    def desktop(self) -> Path:
        return self.root / "usr/share/applications/antigravity-ide.desktop"

    @property
    def launcher(self) -> Path:
        return self.root / "usr/local/bin/antigravity-ide"

    @property
    def legacy_dir(self) -> Path:
        return self.root / "opt/antigravity"


def _sudo(t: Tooling, *argv: str, text: str | None = None) -> bool:
    quiet = {"stdout": subprocess.DEVNULL} if text is not None else {}
    return t.run(["sudo", *argv], input=text, text=True, **quiet).returncode == 0


def _abort(t: Tooling, error: str) -> bool:
    skip(t, error)
    return False


def _tarball_url(arch_dir: str, build: str) -> str:
    return f"https://edgedl.me.gvt1.com/edgedl/release2/j0qc3/antigravity/stable/{build}/{arch_dir}/Antigravity%20IDE.tar.gz"


def resolve_build(t: Tooling, arch_dir: str) -> Resolved:
    t.logger.info("Resolving the latest Antigravity IDE build...")
    pattern = (
        r"https://edgedl\.me\.gvt1\.com/edgedl/release2/[^\"'\\ /]+/antigravity/stable/[0-9][^\"'\\ ]*/"
        + re.escape(arch_dir) + r"/Antigravity%20IDE\.tar\.gz"
    )
    try:
        match = re.search(pattern, t.fetch(DOWNLOAD_PAGE))
    except (OSError, ValueError):
        match = None
    if match is None:
        t.logger.warn("Could not resolve the latest build. Falling back to the pinned URL.")
    url = match.group(0) if match else _tarball_url(arch_dir, PINNED_BUILD)
    build = re.search(r"antigravity/stable/([^/]+)", url).group(1)
    return Resolved(build.split("-")[0], url, f"{build}.tar.gz")


def _find_binary(temp_dir: Path) -> Path | None:
    candidates = [temp_dir / "antigravity-ide", *sorted(temp_dir.glob("*/antigravity-ide"))]
    return next((p for p in candidates if p.is_file()), None)


def fetch_and_extract(t: Tooling, resolved: Resolved, temp_dir: Path) -> Path | None:
    tarball = temp_dir / "antigravity-ide.tar.gz"
    version = resolved.version or "unknown"
    try:
        hit = download_with_cache(t, CACHE_TOOL, resolved, tarball)
    except (OSError, ValueError):
        skip(t, f"Failed to download Antigravity IDE from {resolved.url}")
        return None
    t.logger.info(f"Using cached Antigravity IDE {version} tarball." if hit else f"Downloaded Antigravity IDE {version}.")
    t.logger.info("Extracting Antigravity IDE...")
    try:
        with tarfile.open(tarball) as archive:
            archive.extractall(temp_dir, filter="data")
    except (tarfile.TarError, OSError):
        skip(t, "Failed to extract Antigravity IDE.")
        return None
    binary = _find_binary(temp_dir)
    if binary is None:
        skip(t, "Could not find the antigravity-ide binary in the archive.")
        return None
    return binary.parent


def _fail_placing(t: Tooling, layout: Layout, error: str) -> bool:
    skip(t, error)
    _sudo(t, "rm", "-rf", "--", str(layout.staging_dir))
    return False


def _stage(t: Tooling, layout: Layout, extracted: Path) -> bool:
    staging = layout.staging_dir
    _sudo(t, "rm", "-rf", "--", str(staging))
    if not _sudo(t, "mkdir", "-p", str(staging)):
        return _abort(t, f"Failed to create {staging}.")
    if not _sudo(t, "cp", "-r", f"{extracted}/.", f"{staging}/"):
        return _fail_placing(t, layout, f"Failed to copy Antigravity IDE into {staging}.")
    if not _sudo(t, "chown", "-R", "root:root", str(staging)):
        return _fail_placing(t, layout, f"Failed to set ownership on {staging}.")
    return _set_sandbox_bit(t, layout)


def _set_sandbox_bit(t: Tooling, layout: Layout) -> bool:
    sandbox = layout.staging_dir / "chrome-sandbox"
    if not sandbox.is_file():
        t.logger.warn("chrome-sandbox not found in the Antigravity IDE archive; the sandbox may not start.")
        return True
    # Electron's SUID sandbox helper; without root ownership Ubuntu's userns restriction blocks startup.
    if not _sudo(t, "chmod", "4755", str(sandbox)):
        return _fail_placing(t, layout, "Failed to set the SUID bit on chrome-sandbox.")
    return True


def _swap_into_place(t: Tooling, layout: Layout) -> bool:
    _sudo(t, "mv", "--", str(layout.install_dir), str(layout.old_dir))
    if not _sudo(t, "mv", "--", str(layout.staging_dir), str(layout.install_dir)):
        _fail_placing(t, layout, f"Failed to move staged Antigravity IDE into {layout.install_dir}.")
        if layout.old_dir.is_dir():
            _sudo(t, "mv", "--", str(layout.old_dir), str(layout.install_dir))
        return False
    _sudo(t, "rm", "-rf", "--", str(layout.old_dir))
    return True


def _install_icon(t: Tooling, layout: Layout) -> None:
    source = layout.install_dir / "resources/app/resources/linux/code.png"
    fallback = "the launcher will use a generic icon."
    if not source.is_file():
        t.logger.warn(f"Antigravity IDE icon not found at {source}; {fallback}")
    elif not _sudo(t, "mkdir", "-p", str(layout.icon.parent)):
        t.logger.warn(f"Could not create {layout.icon.parent}; {fallback}")
    elif not _sudo(t, "cp", "--", str(source), str(layout.icon)):
        t.logger.warn(f"Could not write {layout.icon}; {fallback}")
    else:
        _sudo(t, "gtk-update-icon-cache", "-f", "-t", str(layout.icon.parents[2]))


def _wire_up(t: Tooling, layout: Layout, resolved: Resolved) -> bool:
    link = ["ln", "-sfn", str(layout.install_dir / "antigravity-ide"), str(layout.launcher)]
    if not _sudo(t, *link):
        return _abort(t, f"Failed to symlink {layout.launcher}.")
    _install_icon(t, layout)
    entry = DESKTOP_ENTRY.format(install_dir=layout.install_dir)
    if not _sudo(t, "tee", str(layout.desktop), text=entry):
        return _abort(t, f"Failed to write {layout.desktop}.")
    _sudo(t, "update-desktop-database", str(layout.desktop.parent))
    if not _sudo(t, "tee", str(layout.build_file), text=f"{resolved.cache_key.removesuffix('.tar.gz')}\n"):
        return _abort(t, f"Failed to record the installed build in {layout.build_file}.")
    return True


def place(t: Tooling, layout: Layout, extracted: Path, resolved: Resolved) -> bool:
    t.logger.info(f"Installing Antigravity IDE to {layout.install_dir}...")
    if not (_stage(t, layout, extracted) and _swap_into_place(t, layout) and _wire_up(t, layout, resolved)):
        return False
    t.logger.success(f"Antigravity IDE {resolved.version or 'unknown'} installed to {layout.install_dir}.")
    return True


def remove_legacy(t: Tooling, layout: Layout) -> None:
    if not layout.legacy_dir.is_dir():
        return
    _sudo(t, "rm", "-rf", "--", str(layout.legacy_dir))
    _sudo(t, "rm", "-f", "--", str(layout.root / "usr/local/bin/antigravity"),
          str(layout.root / "usr/share/applications/antigravity.desktop"),
          str(layout.root / "usr/share/icons/hicolor/512x512/apps/antigravity.png"))
    _sudo(t, "update-desktop-database", str(layout.desktop.parent))
    t.logger.info("Removed the legacy Antigravity install.")


def _installed_build(layout: Layout) -> str | None:
    try:
        return layout.build_file.read_text().strip()
    except OSError:
        return None


def install_antigravity_ide(t: Tooling, layout: Layout | None = None, machine: str | None = None) -> bool:
    layout = layout or Layout()
    t.logger.info("Installing Antigravity IDE...")
    arch = machine or platform.machine()
    arch_dir = ARCH_DIRS.get(arch)
    if arch_dir is None:
        return skip(t, f"No Antigravity IDE build for architecture {arch}.")
    if dry_run_all(
        t, f"Would resolve the latest Antigravity IDE build from {DOWNLOAD_PAGE}",
        f"Would install Antigravity IDE to {layout.install_dir} with a launcher and desktop entry",
    ):
        return True
    resolved = resolve_build(t, arch_dir)
    if _installed_build(layout) == resolved.cache_key.removesuffix(".tar.gz"):
        t.logger.info(f"Antigravity IDE {resolved.version} is already installed. Skipping.")
        return True
    with tempfile.TemporaryDirectory() as temp_dir:
        extracted = fetch_and_extract(t, resolved, Path(temp_dir))
        if extracted is not None and place(t, layout, extracted, resolved):
            remove_legacy(t, layout)
    return True
