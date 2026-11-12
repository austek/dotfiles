"""Installs tools shipped as release artifacts; a failure at any stage warns and continues."""
from __future__ import annotations

import os
import platform
import re
import shutil
import tarfile
import tempfile
import zipfile
import zlib
from collections.abc import Callable, Collection
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from dotfiles_setup.checksums import ChecksumError, DigestMismatchError, verify_file
from dotfiles_setup.deb_helpers import (
    _dpkg_listing,
    _dpkg_version,
    _install_deb_or_fix_broken,
    _is_older,
)
from dotfiles_setup.release_specs import SpecData, load_specs
from dotfiles_setup.result import Err, Ok
from dotfiles_setup.tooling import Tooling, dry_run_all

MSG_CONTINUING_SETUP = "Continuing with setup..."
SUPPORTED_ARCH = "x86_64"
SPECS_FILE = Path(__file__).resolve().parent.parent.parent / "packages" / "release_specs.json"
EXTRACT_ERRORS = (
    tarfile.TarError, zipfile.BadZipFile, zlib.error, EOFError, NotImplementedError, RuntimeError, OSError,
)


@dataclass(frozen=True)
class Resolved:
    version: str
    url: str
    cache_key: str


@dataclass(frozen=True)
class ReleaseSpec:
    name: str
    is_installed: Callable[[Tooling], bool]
    resolve: Callable[[Tooling], Resolved]
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


def _discard(t: Tooling, cached: Path) -> None:
    try:
        cached.unlink(missing_ok=True)
    except OSError as error:
        t.logger.warn(f"Could not remove {cached}: {error}")


def download_with_cache(
    t: Tooling, tool: str, resolved: Resolved, dest: Path, verify: Callable[[Path], None] = lambda _: None,
) -> bool:
    """`verify` runs on every artifact before it is returned or cached, and raises to refuse it."""
    cache_dir = _cache_dir(t, tool)
    cached = cache_dir / resolved.cache_key
    try:
        if cached.is_file() and cached.stat().st_size > 0:
            shutil.copy(cached, dest)
            verify(dest)
            return True
    except DigestMismatchError as error:
        t.logger.warn(f"Discarding the cached {tool} download: {error}")
        _discard(t, cached)
    except OSError:
        pass
    t.download(resolved.url, dest)
    verify(dest)
    _store_in_cache(cache_dir, resolved.cache_key, dest)
    return False


def skip(t: Tooling, error: str) -> bool:
    t.logger.error(error)
    t.logger.warn(MSG_CONTINUING_SETUP)
    return True


def _extract_zip(artifact: Path, temp_dir: Path) -> None:
    with zipfile.ZipFile(artifact) as archive:
        for info in archive.infolist():
            extracted = Path(archive.extract(info, temp_dir))
            mode = info.external_attr >> 16
            if mode and not info.is_dir():
                extracted.chmod(mode & 0o777)


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
    except EXTRACT_ERRORS as error:
        skip(t, f"Failed to extract {spec.name} {phrase}: {type(error).__name__}: {error}")
        return False
    return True


def _fetch_and_install(t: Tooling, spec: ReleaseSpec, resolved: Resolved, temp_dir: Path) -> None:
    artifact = temp_dir / "artifact"
    suffix = f" v{resolved.version}" if resolved.version else ""
    t.logger.info(f"Fetching {spec.name}{suffix}...")
    try:
        cache_hit = download_with_cache(
            t, spec.name, resolved, artifact, lambda path: verify_file(t.checksums, resolved.url, path),
        )
    except ChecksumError as error:
        skip(t, f"Refusing {spec.name} download: {error}")
        return
    except (OSError, ValueError) as error:
        skip(t, f"Failed to download {spec.name} from {resolved.url}: {error}")
        return
    if cache_hit:
        t.logger.info("(using cached download)")
    if not _unpack(t, spec, artifact, temp_dir):
        return
    if not spec.install(t, temp_dir, artifact, resolved):
        skip(t, f"Failed to install {spec.name}.")
        return
    t.logger.success(f"{spec.name} installed successfully{suffix}.")


def _supported_arch(t: Tooling, spec: ReleaseSpec) -> bool:
    if platform.machine() == SUPPORTED_ARCH:
        return True
    t.logger.warn(f"Skipping {spec.name}: its release is built for {SUPPORTED_ARCH} only.")
    return False


def install_release(t: Tooling, spec: ReleaseSpec) -> bool:
    t.logger.info(f"Installing {spec.name}...")
    if spec.is_installed(t):
        t.logger.info(f"{spec.name} is already installed. Skipping.")
        return True
    if not _supported_arch(t, spec):
        return True
    resolved = spec.resolve(t)
    if dry_run_all(t, f"Would download and install {spec.name} v{resolved.version}"):
        return True
    with tempfile.TemporaryDirectory() as temp_dir:
        _fetch_and_install(t, spec, resolved, Path(temp_dir))
    return True


def _sudo_install(t: Tooling, binary: Path) -> bool:
    return t.run(["sudo", "install", str(binary), "/usr/local/bin"]).returncode == 0


def _istioctl_install(t: Tooling, temp_dir: Path, _artifact: Path, resolved: Resolved) -> bool:
    return _sudo_install(t, temp_dir / f"istio-{resolved.version}" / "bin" / "istioctl")


def _awscli_install(t: Tooling, temp_dir: Path, _artifact: Path, _resolved: Resolved) -> bool:
    return t.run(["sudo", str(temp_dir / "aws" / "install")]).returncode == 0


def _jetbrains_binary(home: Path) -> Path:
    return home / ".local/share/JetBrains/Toolbox/bin/jetbrains-toolbox"


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


def _deb_installed(package: str) -> Callable[[Tooling], bool]:
    return lambda t: re.search(rf"^ii {{2}}{re.escape(package)} ", _dpkg_listing(t), re.MULTILINE) is not None


def _which_installed(binary: str) -> Callable[[Tooling], bool]:
    return lambda t: shutil.which(binary) is not None


def _binary_install(binary: str) -> Callable[[Tooling, Path, Path, Resolved], bool]:
    return lambda t, temp_dir, _artifact, _resolved: _sudo_install(t, temp_dir / binary)


def _deb_install(package: str) -> Callable[[Tooling, Path, Path, Resolved], bool]:
    return lambda t, _dir, artifact, _resolved: _install_deb_or_fix_broken(t, artifact, package)


CUSTOM_BEHAVIOR: dict[str, tuple[Callable[[Tooling], bool], Callable[[Tooling, Path, Path, Resolved], bool]]] = {
    "zoom": (_deb_installed("zoom"), _deb_install("zoom")),
    "jetbrains-toolbox": (lambda t: _jetbrains_binary(t.home).is_file(), _jetbrains_install),
    "istioctl": (_which_installed("istioctl"), _istioctl_install),
    "awscli": (_which_installed("aws"), _awscli_install),
}


def _release_spec(data: SpecData) -> ReleaseSpec:
    resolved = Resolved(data.version, data.download_url, data.artifact_name)
    if data.binary:
        is_installed, install = _which_installed(data.binary), _binary_install(data.binary)
    else:
        is_installed, install = CUSTOM_BEHAVIOR[data.package]
    return ReleaseSpec(data.name, is_installed, lambda _t: resolved, data.kind, install)


def _load_spec_data() -> tuple[SpecData, ...]:
    match load_specs(SPECS_FILE):
        case Err(error=message):
            raise ValueError(message)
        case Ok(value=specs):
            unwired = [d.package for d in specs if not d.binary and d.package not in CUSTOM_BEHAVIOR]
            if unwired:
                raise ValueError(f"{SPECS_FILE} lists packages with no install behavior: {', '.join(unwired)}.")
            return specs


SPEC_DATA: dict[str, SpecData] = {d.package: d for d in _load_spec_data()}
RELEASE_SPECS: tuple[tuple[str, ReleaseSpec], ...] = tuple((p, _release_spec(d)) for p, d in SPEC_DATA.items())
RELEASE_INSTALLERS: tuple[tuple[str, Callable[[Tooling], bool]], ...] = tuple(
    (package, lambda t, spec=spec: install_release(t, spec)) for package, spec in RELEASE_SPECS
)
_SPECS = dict(RELEASE_SPECS)
LAZYDOCKER, ZOOM, JETBRAINS_TOOLBOX = (_SPECS[p] for p in ("lazydocker", "zoom", "jetbrains-toolbox"))
ISTIOCTL, AWSCLI, ZIZMOR, MCP_GRAFANA = (_SPECS[p] for p in ("istioctl", "awscli", "zizmor", "mcp-grafana"))
UPGRADABLE_DEBS: tuple[tuple[str, ReleaseSpec], ...] = (("zoom", ZOOM),)


def upgrade_release(t: Tooling, spec: ReleaseSpec, package: str) -> None:
    installed = _dpkg_version(t, package)
    if installed is None or not _supported_arch(t, spec):
        return
    resolved = spec.resolve(t)
    older = _is_older(t, installed, resolved.version)
    if older is None:
        t.logger.warn(f"Could not compare {spec.name} v{installed} with the pinned v{resolved.version}. Skipping upgrade.")
        return
    if not older:
        t.logger.info(f"{spec.name} v{installed} is not older than the pinned v{resolved.version}. Skipping.")
        return
    if dry_run_all(t, f"Would upgrade {spec.name} from v{installed} to v{resolved.version}"):
        return
    with tempfile.TemporaryDirectory() as temp_dir:
        _fetch_and_install(t, spec, resolved, Path(temp_dir))


def upgrade_vendor_debs(t: Tooling, package_names: Collection[str]) -> None:
    """Installs the pinned version of each wanted vendor .deb whose installed version is older than the pin."""
    for package, spec in UPGRADABLE_DEBS:
        if package in package_names:
            upgrade_release(t, spec, package)
