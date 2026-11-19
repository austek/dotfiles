"""Installs tools shipped as release artifacts; a failure at any stage warns and continues."""
from __future__ import annotations

import hashlib
import os
import platform
import re
import shutil
import subprocess
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
from dotfiles_setup.fsutil import install_executable, link_executable
from dotfiles_setup.release_specs import SpecData, load_specs
from dotfiles_setup.result import Err, Ok
from dotfiles_setup.rollback import RollbackLog
from dotfiles_setup.tooling import Tooling, dry_run_all

MSG_CONTINUING_SETUP = "Continuing with setup..."
SUPPORTED_ARCH = "x86_64"
SYSTEM_BIN_DIR = Path("/usr/local/bin")
VERSION_PROBE_TIMEOUT_SECONDS = 10
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
    kind: Literal["targz", "zip", "deb", "binary"]
    install: Callable[[Tooling, Path, Path, Resolved], bool]
    binary: str | None = None
    begin_tracking: Callable[[Tooling, ReleaseSpec, RollbackLog | None], Callable[[], None]] | None = None


def user_bin_dir(t: Tooling) -> Path:
    return t.home / ".local" / "bin"


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


def _track_binary(t: Tooling, spec: ReleaseSpec, changes: RollbackLog | None) -> Callable[[], None]:
    def record() -> None:
        if changes is None or spec.binary is None:
            return
        target = user_bin_dir(t) / spec.binary
        digest = hashlib.sha256(target.read_bytes()).hexdigest()
        changes.track(f"BIN_INSTALLED:{target}|{digest}", dry_run=t.logger.dry_run)

    return record


def _fetch_and_install(
    t: Tooling, spec: ReleaseSpec, resolved: Resolved, temp_dir: Path, changes: RollbackLog | None = None,
) -> None:
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
    record = (spec.begin_tracking or _track_binary)(t, spec, changes)
    if not spec.install(t, temp_dir, artifact, resolved):
        skip(t, f"Failed to install {spec.name}.")
        return
    record()
    t.logger.success(f"{spec.name} installed successfully{suffix}.")


def _supported_arch(t: Tooling, spec: ReleaseSpec) -> bool:
    if platform.machine() == SUPPORTED_ARCH:
        return True
    t.logger.warn(f"Skipping {spec.name}: its release is built for {SUPPORTED_ARCH} only.")
    return False


def install_release(t: Tooling, spec: ReleaseSpec, changes: RollbackLog | None = None) -> None:
    t.logger.info(f"Installing {spec.name}...")
    if spec.is_installed(t):
        t.logger.info(f"{spec.name} is already installed. Skipping.")
        return
    if not _supported_arch(t, spec):
        return
    resolved = spec.resolve(t)
    if dry_run_all(t, f"Would download and install {spec.name} v{resolved.version}"):
        return
    with tempfile.TemporaryDirectory() as temp_dir:
        _fetch_and_install(t, spec, resolved, Path(temp_dir), changes)


def aws_cli_root(t: Tooling) -> Path:
    return t.home / ".local" / "aws-cli"


def _awscli_install(t: Tooling, temp_dir: Path, _artifact: Path, _resolved: Resolved) -> bool:
    argv = [str(temp_dir / "aws" / "install"), "-i", str(aws_cli_root(t)), "-b", str(user_bin_dir(t)), "--update"]
    return t.run(argv).returncode == 0 and _ensure_aws_link(t)


def _aws_executable(root: Path) -> Path | None:
    candidates = [root / "v2" / "current" / "bin" / "aws", *sorted(root.glob("v2/*/bin/aws"), reverse=True)]
    return next((path for path in candidates if path.is_file()), None)


def _ensure_aws_link(t: Tooling) -> bool:
    """The installer exits 0 without linking when the pinned tree already exists, so a missing link is restored here."""
    link = user_bin_dir(t) / "aws"
    if link.exists():
        return True
    executable = _aws_executable(aws_cli_root(t))
    if executable is None:
        t.logger.error(f"The AWS CLI installer left no aws executable under {aws_cli_root(t)}; {link} was not linked.")
        return False
    match link_executable(executable, "aws", link.parent):
        case Err(error=message):
            t.logger.error(message)
            return False
        case _:
            return True


def _link_exists(link: Path) -> bool:
    return link.is_symlink() or link.exists()


def _awscli_tracking(t: Tooling, _spec: ReleaseSpec, changes: RollbackLog | None) -> Callable[[], None]:
    """Captured before the install: an existing tree is not ours to remove on rollback, so it is not tracked, and neither is a link that was already there."""
    root, bin_dir = aws_cli_root(t), user_bin_dir(t)
    action = "LINK_INSTALLED" if root.exists() else "TREE_INSTALLED"
    existed = {name: _link_exists(bin_dir / name) for name in ("aws", "aws_completer")}

    def created(name: str) -> bool:
        return not existed[name] and _link_exists(bin_dir / name)

    def record() -> None:
        if changes is None:
            return
        if action == "TREE_INSTALLED" or created("aws"):
            changes.track(f"{action}:{root}|{bin_dir / 'aws'}", dry_run=t.logger.dry_run)
        if created("aws_completer"):
            changes.track(f"LINK_INSTALLED:{root}|{bin_dir / 'aws_completer'}", dry_run=t.logger.dry_run)

    return record


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


def _user_bin_install(t: Tooling, source: Path, binary: str) -> bool:
    target = user_bin_dir(t) / binary
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        install_executable(source, target)
    except OSError as error:
        t.logger.error(f"Could not write {target}: {error}")
        return False
    return True


def _binary_install(binary: str) -> Callable[[Tooling, Path, Path, Resolved], bool]:
    def install(t: Tooling, temp_dir: Path, _artifact: Path, _resolved: Resolved) -> bool:
        found = sorted((p for p in temp_dir.rglob(binary) if p.is_file()), key=lambda p: (len(p.parts), str(p)))
        return bool(found) and _user_bin_install(t, found[0], binary)

    return install


def _raw_binary_install(binary: str) -> Callable[[Tooling, Path, Path, Resolved], bool]:
    return lambda t, _dir, artifact, _resolved: _user_bin_install(t, artifact, binary)


def _user_bin_installed(binary: str) -> Callable[[Tooling], bool]:
    return lambda t: (user_bin_dir(t) / binary).is_file()


def _deb_install(package: str) -> Callable[[Tooling, Path, Path, Resolved], bool]:
    return lambda t, _dir, artifact, _resolved: _install_deb_or_fix_broken(t, artifact, package)


CUSTOM_BEHAVIOR: dict[str, tuple[Callable[[Tooling], bool], Callable[[Tooling, Path, Path, Resolved], bool]]] = {
    "zoom": (_deb_installed("zoom"), _deb_install("zoom")),
    "jetbrains-toolbox": (lambda t: _jetbrains_binary(t.home).is_file(), _jetbrains_install),
    "awscli": (_user_bin_installed("aws"), _awscli_install),
}
CUSTOM_BINARY_NAMES = {"awscli": "aws"}
CUSTOM_TRACKING = {"awscli": _awscli_tracking}


def _behavior(data: SpecData) -> tuple[Callable[[Tooling], bool], Callable[[Tooling, Path, Path, Resolved], bool]]:
    if data.package in CUSTOM_BEHAVIOR:
        return CUSTOM_BEHAVIOR[data.package]
    binary = data.binary or data.package
    place = _raw_binary_install if data.kind == "binary" else _binary_install
    return _user_bin_installed(binary), place(binary)


def _release_spec(data: SpecData) -> ReleaseSpec:
    resolved = Resolved(data.version, data.download_url, data.artifact_name)
    is_installed, install = _behavior(data)
    binary = CUSTOM_BINARY_NAMES.get(data.package, data.binary)
    return ReleaseSpec(
        data.name, is_installed, lambda _t: resolved, data.kind, install, binary, CUSTOM_TRACKING.get(data.package),
    )


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
PRIVILEGED_PACKAGES = frozenset({"zoom"})
USER_BINARY_SPECS = tuple((p, s) for p, s in RELEASE_SPECS if s.binary)
USER_SPECS = tuple((p, s) for p, s in RELEASE_SPECS if p not in PRIVILEGED_PACKAGES and not s.binary)
SYSTEM_SPECS = tuple((p, s) for p, s in RELEASE_SPECS if p in PRIVILEGED_PACKAGES)


def _installers(specs: tuple[tuple[str, ReleaseSpec], ...]) -> tuple[tuple[str, Callable[[Tooling], None]], ...]:
    return tuple((package, lambda t, spec=spec: install_release(t, spec)) for package, spec in specs)


USER_RELEASE_INSTALLERS = _installers(USER_SPECS)
SYSTEM_RELEASE_INSTALLERS = _installers(SYSTEM_SPECS)
_SPECS = dict(RELEASE_SPECS)
LAZYDOCKER, ZOOM, JETBRAINS_TOOLBOX = (_SPECS[p] for p in ("lazydocker", "zoom", "jetbrains-toolbox"))
ISTIOCTL, AWSCLI, ZIZMOR, MCP_GRAFANA = (_SPECS[p] for p in ("istioctl", "awscli", "zizmor", "mcp-grafana"))
CHIP = _SPECS["chip"]
UPGRADABLE_DEBS: tuple[tuple[str, ReleaseSpec], ...] = (("zoom", ZOOM),)
UPGRADABLE_BINARIES: tuple[tuple[str, ReleaseSpec], ...] = (("chip", CHIP),)


def _binary_version(t: Tooling, binary: str) -> str | None:
    """Version of `~/.local/bin/<binary>` without a leading `v`. None when the file is absent or the probe exits non-zero or prints nothing."""
    managed = user_bin_dir(t) / binary
    if not managed.is_file():
        return None
    try:
        result = t.run([str(managed), "--version"], capture_output=True, text=True, timeout=VERSION_PROBE_TIMEOUT_SECONDS)
    except (subprocess.TimeoutExpired, OSError):
        return None
    lines = (result.stdout or "").strip().splitlines() if result.returncode == 0 else []
    return lines[0].strip().removeprefix("v") if lines else None


def upgrade_release(t: Tooling, spec: ReleaseSpec, installed: str | None) -> None:
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


def ensure_user_bin_dir(t: Tooling, changes: RollbackLog | None) -> bool:
    """Creates `~/.local/bin` (mode 0755) and tracks it for rollback; False, with a warning, when it cannot be made."""
    target = user_bin_dir(t)
    if target.is_dir() or t.logger.dry_run:
        return True
    try:
        target.mkdir(parents=True)
        target.chmod(0o755)
    except OSError as error:
        t.logger.warn(f"Could not create {target}: {error}")
        return False
    if changes is not None:
        changes.track(f"DIR_CREATED:{target}", dry_run=False)
    return True


def _user_bin_dir_ready(t: Tooling, wanted: list[ReleaseSpec], changes: RollbackLog | None) -> bool:
    missing = platform.machine() == SUPPORTED_ARCH and any(not spec.is_installed(t) for spec in wanted)
    return ensure_user_bin_dir(t, changes) if missing else True


def install_user_binaries(
    t: Tooling, package_names: Collection[str], changes: RollbackLog | None = None,
) -> bool:
    """Installs each wanted pinned binary that is missing from `~/.local/bin`, with no sudo. False when the directory cannot be created."""
    wanted = [spec for package, spec in USER_BINARY_SPECS if package in package_names]
    if not _user_bin_dir_ready(t, wanted, changes):
        return False
    for spec in wanted:
        install_release(t, spec, changes)
    return True


def upgrade_user_binaries(t: Tooling, package_names: Collection[str]) -> None:
    """Installs the pin of each wanted upgradable binary whose installed version is older, never a downgrade."""
    for package, spec in UPGRADABLE_BINARIES:
        if package in package_names:
            upgrade_release(t, spec, _binary_version(t, SPEC_DATA[package].binary or package))


def pending_system_releases(t: Tooling, package_names: Collection[str]) -> list[str]:
    """Names of wanted sudo-installed releases that are absent; empty on an unsupported architecture."""
    if platform.machine() != SUPPORTED_ARCH:
        return []
    return [p for p, spec in SYSTEM_SPECS if p in package_names and not spec.is_installed(t)]


def upgrade_vendor_debs(t: Tooling, package_names: Collection[str]) -> None:
    """Installs the pinned version of each wanted vendor .deb whose installed version is older than the pin."""
    for package, spec in UPGRADABLE_DEBS:
        if package in package_names:
            upgrade_release(t, spec, _dpkg_version(t, package))
