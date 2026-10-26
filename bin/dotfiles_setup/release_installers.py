"""Installs tools shipped as release artifacts; a failure at any stage warns and continues."""
from __future__ import annotations

import os
import re
import shutil
import tarfile
import tempfile
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from dotfiles_setup.tooling import Tooling, dry_run_all

MSG_CONTINUING_SETUP = "Continuing with setup..."
LAZYDOCKER_API = "https://api.github.com/repos/jesseduffield/lazydocker/releases/latest"
ZOOM_URL = "https://zoom.us/client/latest/zoom_amd64.deb"
SLACK_PAGE = "https://slack.com/downloads/linux"
JETBRAINS_API = "https://data.services.jetbrains.com/products/releases?code=TBA&latest=true&type=release"
SLACK_APT_SOURCES = ("/etc/apt/sources.list.d/slack.sources", "/etc/apt/sources.list.d/slack.list")


@dataclass(frozen=True)
class Resolved:
    version: str
    url: str
    cache_key: str


@dataclass(frozen=True)
class ReleaseSpec:
    name: str
    is_installed: Callable[[Tooling], bool]
    resolve: Callable[[Tooling], Resolved | None]
    kind: Literal["targz", "zip", "deb"]
    install: Callable[[Tooling, Path, Path, Resolved], bool]


def _cache_dir(t: Tooling, tool: str) -> Path:
    root = Path(os.environ.get("XDG_CACHE_HOME") or t.home / ".cache")
    return root / "dotfiles-setup" / tool


def _store_in_cache(cache_dir: Path, cache_key: str, artifact: Path) -> None:
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
        partial = cache_dir / f".{cache_key}.tmp"
        shutil.copy(artifact, partial)
        partial.replace(cache_dir / cache_key)
        for stale in cache_dir.iterdir():
            if stale.is_file() and stale.name != cache_key and not stale.name.startswith("."):
                stale.unlink()
    except OSError:
        pass


def download_with_cache(t: Tooling, tool: str, resolved: Resolved, dest: Path) -> bool:
    cache_dir = _cache_dir(t, tool)
    cached = cache_dir / resolved.cache_key
    try:
        if cached.is_file() and cached.stat().st_size > 0:
            shutil.copy(cached, dest)
            return True
    except OSError:
        pass
    t.download(resolved.url, dest)
    _store_in_cache(cache_dir, resolved.cache_key, dest)
    return False


def skip(t: Tooling, error: str) -> bool:
    t.logger.error(error)
    t.logger.warn(MSG_CONTINUING_SETUP)
    return True


def _extract_zip(artifact: Path, temp_dir: Path) -> None:
    with zipfile.ZipFile(artifact) as archive:
        archive.extractall(temp_dir)
        for info in archive.infolist():
            mode = info.external_attr >> 16
            if mode:
                (temp_dir / info.filename).chmod(mode & 0o777)


def _extract_targz(artifact: Path, temp_dir: Path) -> None:
    with tarfile.open(artifact) as archive:
        archive.extractall(temp_dir, filter="data")


def _unpack(t: Tooling, spec: ReleaseSpec, artifact: Path, temp_dir: Path) -> bool:
    extractors = {"targz": (_extract_targz, "from tarball"), "zip": (_extract_zip, "installer")}
    if spec.kind not in extractors:
        return True
    extract, phrase = extractors[spec.kind]
    try:
        extract(artifact, temp_dir)
    except (tarfile.TarError, zipfile.BadZipFile, OSError):
        skip(t, f"Failed to extract {spec.name} {phrase}.")
        return False
    return True


def _fetch_and_install(t: Tooling, spec: ReleaseSpec, resolved: Resolved, temp_dir: Path) -> None:
    artifact = temp_dir / "artifact"
    suffix = f" v{resolved.version}" if resolved.version else ""
    t.logger.info(f"Fetching {spec.name}{suffix}...")
    try:
        cache_hit = download_with_cache(t, spec.name, resolved, artifact)
    except (OSError, ValueError):
        skip(t, f"Failed to download {spec.name} from {resolved.url}")
        return
    if cache_hit:
        t.logger.info("(using cached download)")
    if not _unpack(t, spec, artifact, temp_dir):
        return
    if not spec.install(t, temp_dir, artifact, resolved):
        skip(t, f"Failed to install {spec.name}.")
        return
    t.logger.success(f"{spec.name} installed successfully{suffix}.")


def install_release(t: Tooling, spec: ReleaseSpec) -> bool:
    t.logger.info(f"Installing {spec.name}...")
    if spec.is_installed(t):
        t.logger.info(f"{spec.name} is already installed. Skipping.")
        return True
    if dry_run_all(t, f"Would fetch {spec.name} latest release", f"Would download and install {spec.name}"):
        return True
    resolved = spec.resolve(t)
    if resolved is None:
        return skip(t, f"Failed to resolve {spec.name} download URL.")
    with tempfile.TemporaryDirectory() as temp_dir:
        _fetch_and_install(t, spec, resolved, Path(temp_dir))
    return True


def _fetch_or_none(t: Tooling, url: str) -> str | None:
    try:
        return t.fetch(url)
    except (OSError, ValueError):
        return None


def _dpkg_listing(t: Tooling) -> str:
    return t.run(["dpkg", "-l"], capture_output=True, text=True).stdout or ""


def _dpkg_has(t: Tooling, pattern: str) -> bool:
    return re.search(rf"^ii.*{pattern}", _dpkg_listing(t), re.MULTILINE) is not None


def _install_deb_or_fix_broken(t: Tooling, deb: Path, package_pattern: str) -> bool:
    if t.logger.quiet_run(["sudo", "dpkg", "-i", str(deb)], run=t.run).returncode == 0:
        return True
    t.logger.warn("dpkg reported errors. Running 'apt --fix-broken install'...")
    t.logger.quiet_run(["sudo", "apt-get", "-y", "--fix-broken", "install"], run=t.run)
    return _dpkg_has(t, package_pattern)


def _lazydocker_resolve(t: Tooling) -> Resolved | None:
    body = _fetch_or_none(t, LAZYDOCKER_API)
    match = re.search(r'"tag_name":\s*"v([^"]*)"', body or "")
    if not match:
        return None
    version = match.group(1)
    base = "https://github.com/jesseduffield/lazydocker/releases/latest/download"
    return Resolved(version, f"{base}/lazydocker_{version}_Linux_x86_64.tar.gz", f"{version}.tar.gz")


def _sudo_install(t: Tooling, binary: Path) -> bool:
    return t.run(["sudo", "install", str(binary), "/usr/local/bin"]).returncode == 0


def _github_tag(t: Tooling, repo: str) -> str | None:
    match = re.search(r'"tag_name":\s*"([^"]*)"', _fetch_or_none(t, f"https://api.github.com/repos/{repo}/releases/latest") or "")
    return match.group(1) if match else None


def _istioctl_resolve(t: Tooling) -> Resolved | None:
    tag = _github_tag(t, "istio/istio")
    if not tag:
        return None
    url = f"https://github.com/istio/istio/releases/download/{tag}/istio-{tag}-linux-amd64.tar.gz"
    return Resolved(tag, url, f"istio-{tag}-linux-amd64.tar.gz")


def _istioctl_install(t: Tooling, temp_dir: Path, _artifact: Path, resolved: Resolved) -> bool:
    return _sudo_install(t, temp_dir / f"istio-{resolved.version}" / "bin" / "istioctl")


def _awscli_resolve(_t: Tooling) -> Resolved:
    # AWS exposes no version endpoint; the fixed cache key is safe because this only runs while `aws` is absent.
    return Resolved("", "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip", "awscliv2.zip")


def _awscli_install(t: Tooling, temp_dir: Path, _artifact: Path, _resolved: Resolved) -> bool:
    return t.run(["sudo", str(temp_dir / "aws" / "install")]).returncode == 0


def _github_binary_spec(name: str, repo: str, asset: str, binary: str) -> ReleaseSpec:
    def resolve(t: Tooling) -> Resolved | None:
        tag = _github_tag(t, repo)
        if not tag:
            return None
        return Resolved(tag, f"https://github.com/{repo}/releases/download/{tag}/{asset}", f"{name}-{tag}.tar.gz")

    return ReleaseSpec(
        name, lambda t: shutil.which(binary) is not None, resolve, "targz",
        lambda t, temp_dir, _artifact, _resolved: _sudo_install(t, temp_dir / binary),
    )


def _lazydocker_install(t: Tooling, temp_dir: Path, _artifact: Path, _resolved: Resolved) -> bool:
    return _sudo_install(t, temp_dir / "lazydocker")


def _zoom_resolve(t: Tooling) -> Resolved:
    location = t.redirect(ZOOM_URL) or ""
    match = re.search(r"/prod/([0-9.]+)", location)
    version = match.group(1) if match else "latest"
    return Resolved(version, ZOOM_URL, f"zoom_amd64-{version}.deb")


def _slack_resolve(t: Tooling) -> Resolved | None:
    match = re.search(r"Version (\d+\.\d+\.\d+)", _fetch_or_none(t, SLACK_PAGE) or "")
    if not match:
        return None
    version = match.group(1)
    url = f"https://downloads.slack-edge.com/desktop-releases/linux/x64/{version}/slack-desktop-{version}-amd64.deb"
    return Resolved(version, url, f"slack-desktop-{version}-amd64.deb")


def _slack_install(t: Tooling, _temp_dir: Path, artifact: Path, _resolved: Resolved) -> bool:
    installed = _install_deb_or_fix_broken(t, artifact, "slack-desktop")
    # The postinst apt repo file has no Signed-By key and trips apt's warning; updates come from the .deb.
    t.run(["sudo", "rm", "-f", *SLACK_APT_SOURCES])
    return installed


def _jetbrains_binary(home: Path) -> Path:
    return home / ".local/share/JetBrains/Toolbox/bin/jetbrains-toolbox"


def _jetbrains_resolve(t: Tooling) -> Resolved | None:
    match = re.search(r'"linux":\{"link":"([^"]+)"', _fetch_or_none(t, JETBRAINS_API) or "")
    if not match:
        return None
    return Resolved("", match.group(1), match.group(1).rsplit("/", 1)[-1])


def _jetbrains_install(t: Tooling, temp_dir: Path, _artifact: Path, _resolved: Resolved) -> bool:
    binary = next((p for p in sorted(temp_dir.rglob("jetbrains-toolbox")) if p.is_file()), None)
    if binary is None:
        t.logger.error("Could not find jetbrains-toolbox binary in archive.")
        return False
    target = _jetbrains_binary(t.home).parent
    try:
        target.mkdir(parents=True, exist_ok=True)
        shutil.copytree(binary.parent, target, dirs_exist_ok=True)
        (target / "jetbrains-toolbox").chmod(0o755)
    except OSError:
        return False
    return True


LAZYDOCKER = ReleaseSpec(
    "lazydocker", lambda t: shutil.which("lazydocker") is not None, _lazydocker_resolve, "targz", _lazydocker_install,
)
ZOOM = ReleaseSpec(
    "Zoom", lambda t: re.search(r"^ii {2}zoom ", _dpkg_listing(t), re.MULTILINE) is not None,
    _zoom_resolve, "deb", lambda t, _dir, artifact, _resolved: _install_deb_or_fix_broken(t, artifact, "zoom"),
)
ISTIOCTL = ReleaseSpec(
    "istioctl", lambda t: shutil.which("istioctl") is not None, _istioctl_resolve, "targz", _istioctl_install,
)
AWSCLI = ReleaseSpec(
    "AWS CLI", lambda t: shutil.which("aws") is not None, _awscli_resolve, "zip", _awscli_install,
)
ZIZMOR = _github_binary_spec("zizmor", "zizmorcore/zizmor", "zizmor-x86_64-unknown-linux-gnu.tar.gz", "zizmor")
MCP_GRAFANA = _github_binary_spec("mcp-grafana", "grafana/mcp-grafana", "mcp-grafana_Linux_x86_64.tar.gz", "mcp-grafana")
SLACK = ReleaseSpec(
    "Slack", lambda t: re.search(r"^ii {2}slack-desktop ", _dpkg_listing(t), re.MULTILINE) is not None,
    _slack_resolve, "deb", _slack_install,
)
JETBRAINS_TOOLBOX = ReleaseSpec(
    "JetBrains Toolbox", lambda t: _jetbrains_binary(t.home).is_file(),
    _jetbrains_resolve, "targz", _jetbrains_install,
)

RELEASE_INSTALLERS: tuple[tuple[str, Callable[[Tooling], bool]], ...] = tuple(
    (package, lambda t, spec=spec: install_release(t, spec))
    for package, spec in (
        ("lazydocker", LAZYDOCKER),
        ("zoom", ZOOM),
        ("slack-desktop", SLACK),
        ("jetbrains-toolbox", JETBRAINS_TOOLBOX),
        ("istioctl", ISTIOCTL),
        ("awscli", AWSCLI),
        ("zizmor", ZIZMOR),
        ("mcp-grafana", MCP_GRAFANA),
    )
)
