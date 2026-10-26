"""Configures the third-party apt repositories: keys, PPAs, stowed sources and rendered templates."""
from __future__ import annotations

import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from dotfiles_setup.system_steps import SystemContext
from dotfiles_setup.tooling import dry_run_all

FS_ROOT = Path("/")
RENDERED_MARKER ="# Managed by dotfiles: rendered from apt-templates"
DEFAULT_CODENAME = "noble"
STOW_BACKUP_ROOT = Path("/var/backups/dotfiles-stow")
SOURCE_FILES = (
    ("1password", "1password.sources"),
    ("google-chrome-stable", "google-chrome.sources"),
    ("code", "vscode.sources"),
    ("gh", "github-cli.sources"),
)
DIRECTORIES = (
    "/usr/share/keyrings",
    "/etc/debsig/policies/AC2D62742012EA22",
    "/usr/share/debsig/keyrings/AC2D62742012EA22",
)
FIREFOX_PIN = "\nPackage: firefox*\nPin: release o=LP-PPA-mozillateam\nPin-Priority: 1001\n\n"
_CONFLICT_PATTERNS = (
    re.compile(r"existing target.*?:\s*(\S+)"),
    re.compile(r"existing target\s+(\S+)\s+since"),
)


@dataclass(frozen=True)
class KeySpec:
    label: str
    url: str
    destinations: tuple[str, ...]
    package: str
    prefix: bool = False

    @property
    def notice(self) -> str:
        return f"Would download {self.label} GPG {'keys' if len(self.destinations) > 1 else 'key'}"


KEYS = (
    KeySpec("Google Chrome", "https://dl.google.com/linux/linux_signing_key.pub",
            ("/usr/share/keyrings/google-chrome-keyring.gpg",), "google-chrome-stable"),
    KeySpec("VS Code", "https://packages.microsoft.com/keys/microsoft.asc",
            ("/usr/share/keyrings/packages.microsoft.gpg",), "code"),
    KeySpec("1Password", "https://downloads.1password.com/linux/keys/1password.asc",
            ("/usr/share/keyrings/1password-archive-keyring.gpg",
             "/usr/share/debsig/keyrings/AC2D62742012EA22/debsig.gpg"), "1password"),
    KeySpec("Docker", "https://download.docker.com/linux/ubuntu/gpg", ("/usr/share/keyrings/docker.gpg",), "docker-ce"),
    KeySpec("GitHub CLI", "https://cli.github.com/packages/githubcli-archive-keyring.gpg",
            ("/usr/share/keyrings/githubcli-archive-keyring.gpg",), "gh"),
    KeySpec("Teleport", "https://apt.releases.teleport.dev/gpg",
            ("/usr/share/keyrings/teleport-archive-keyring.gpg",), "teleport", prefix=True),
    KeySpec("pgAdmin", "https://www.pgadmin.org/static/packages_pgadmin_org.pub",
            ("/usr/share/keyrings/pgadmin4-archive-keyring.gpg",), "pgadmin4", prefix=True),
    KeySpec("PostgreSQL", "https://www.postgresql.org/media/keys/ACCC4CF8.asc",
            ("/usr/share/keyrings/postgresql-archive-keyring.gpg",), "postgresql", prefix=True),
)
ONEPASSWORD_POLICY = ("https://downloads.1password.com/linux/debian/debsig/1password.pol",
                      "/etc/debsig/policies/AC2D62742012EA22/1password.pol")


def _selected(ctx: SystemContext, name: str, prefix: bool = False) -> bool:
    if prefix:
        return any(package.startswith(name) for package in ctx.packages)
    return name in ctx.packages


def _write_as_root(ctx: SystemContext, destination: str, content: str) -> bool:
    result = ctx.t.run(["sudo", "tee", destination], input=content, text=True, stdout=subprocess.DEVNULL)
    return result.returncode == 0


def _dearmor(ctx: SystemContext, url: str, destination: str) -> bool:
    try:
        key = ctx.t.fetch_bytes(url)
    except (OSError, ValueError) as error:
        ctx.t.logger.error(f"Could not download the signing key {url}: {error}")
        return False
    return ctx.t.run(["sudo", "gpg", "--dearmor", "--yes", "-o", destination], input=key).returncode == 0


def download_apt_gpg_keys(ctx: SystemContext) -> bool:
    ctx.t.logger.info("Downloading all required GPG keys...")
    for key in (k for k in KEYS if _selected(ctx, k.package, k.prefix)):
        if dry_run_all(ctx.t, key.notice):
            continue
        if not all(_dearmor(ctx, key.url, destination) for destination in key.destinations):
            return False
    return True


def configure_apt_ppas(ctx: SystemContext) -> bool:
    ctx.t.logger.info("Adding and configuring APT repositories...")
    return _add_firefox_ppa(ctx) and _add_ghostty_ppa(ctx) and _add_1password_policy(ctx)


def _add_firefox_ppa(ctx: SystemContext) -> bool:
    if not _selected(ctx, "firefox") or dry_run_all(ctx.t, "Would add Mozilla PPA and configure Firefox pinning"):
        return True
    return ctx.quiet("sudo", "add-apt-repository", "-y", "ppa:mozillateam/ppa") and _write_as_root(
        ctx, "/etc/apt/preferences.d/mozillateam-firefox-pin", FIREFOX_PIN,
    )


def _add_ghostty_ppa(ctx: SystemContext) -> bool:
    if not _selected(ctx, "ghostty") or dry_run_all(ctx.t, "Would add ghostty PPA (ppa:mkasberg/ghostty-ubuntu)"):
        return True
    return ctx.quiet("sudo", "add-apt-repository", "-y", "ppa:mkasberg/ghostty-ubuntu")


def _add_1password_policy(ctx: SystemContext) -> bool:
    if not _selected(ctx, "1password") or dry_run_all(ctx.t, "Would configure 1Password debsig policy"):
        return True
    return _install_policy(ctx, *ONEPASSWORD_POLICY)


def _install_policy(ctx: SystemContext, url: str, destination: str) -> bool:
    try:
        policy = ctx.t.fetch(url)
    except (OSError, ValueError) as error:
        ctx.t.logger.error(f"Could not download {url}: {error}")
        return False
    return _write_as_root(ctx, destination, policy)


def _stow_ignores(ctx: SystemContext) -> list[str]:
    ignores = []
    for package, source_file in SOURCE_FILES:
        if package not in ctx.packages:
            ctx.t.logger.info(f"Skipping unneeded source file: {source_file}")
            ignores.append("--ignore=" + source_file.replace(".", r"\.") + "$")
    return ignores


def _stow_apt(ctx: SystemContext, ignores: list[str], *flags: str):
    argv = ["sudo", "stow", f"--dir={ctx.dotfiles_dir}", *flags, "--no-folding", *ignores,
            "--target=/", "--verbose=1", "apt"]
    return ctx.t.run(argv, capture_output=True, text=True, cwd=ctx.dotfiles_dir)


def _conflicting_files(simulation: str) -> list[str]:
    found = []
    for line in simulation.splitlines():
        for pattern in _CONFLICT_PATTERNS:
            if match := pattern.search(line):
                found.append(match.group(1))
                break
    return found


def _show_stow_output(ctx: SystemContext, output: str, failed: bool) -> None:
    kept = "\n".join(line for line in output.splitlines() if "WARNING" not in line and "existing target" not in line)
    if kept and (ctx.t.logger.verbosity >= 2 or failed):
        print(kept)


def _resolve_stow_conflicts(ctx: SystemContext, ignores: list[str]) -> bool:
    ctx.t.logger.warn("Stow encountered conflicts. Attempting to resolve...")
    simulation = _stow_apt(ctx, ignores, "--no")
    conflicts = _conflicting_files((simulation.stdout or "") + (simulation.stderr or ""))
    if not conflicts:
        return True
    ctx.t.run(["sudo", "mkdir", "-p", str(STOW_BACKUP_ROOT)])
    for conflict in conflicts:
        existing = FS_ROOT / conflict
        if not existing.is_file():
            continue
        ctx.t.logger.info(f"Backing up conflicting file: {conflict}")
        backup = f"{STOW_BACKUP_ROOT}/{existing.name}.backup-{int(time.time())}"
        if ctx.t.run(["sudo", "mv", str(existing), backup]).returncode != 0:
            return False
        ctx.track(f"FILE_BACKUP:{backup}|{existing}")
    if not ctx.quiet("sudo", "stow", f"--dir={ctx.dotfiles_dir}", "--restow", "--no-folding", *ignores,
                     "--target=/", "--verbose=1", "apt", cwd=ctx.dotfiles_dir):
        return False
    ctx.track("STOW_ROOT:apt")
    return True


def stow_apt_source_files(ctx: SystemContext) -> bool:
    ignores = _stow_ignores(ctx)
    ctx.t.logger.info("Stowing required 'apt' source files to / ...")
    result = _stow_apt(ctx, ignores, "--restow")
    failed = result.returncode != 0
    _show_stow_output(ctx, (result.stdout or "") + (result.stderr or ""), failed)
    if failed:
        return _resolve_stow_conflicts(ctx, ignores)
    ctx.track("STOW_ROOT:apt")
    return True


def detect_ubuntu_codename(ctx: SystemContext, os_release: Path = Path("/etc/os-release")) -> str:
    try:
        match = re.search(r'^VERSION_CODENAME=["\']?([^"\'\n]*)', os_release.read_text(), re.MULTILINE)
    except OSError:
        match = None
    codename = match.group(1) if match else ""
    if not codename:
        ctx.t.logger.warn(f"Could not detect Ubuntu codename; defaulting to '{DEFAULT_CODENAME}'.")
        return DEFAULT_CODENAME
    return codename


def render_apt_template(ctx: SystemContext, name: str, codename: str, sources_dir: Path) -> bool:
    ctx.t.logger.info(f"Configuring {name} apt repository for suite: {codename}")
    template = (ctx.dotfiles_dir / "apt-templates" / f"{name}.sources.template").read_text()
    destination = sources_dir / f"{name}.sources"
    if not _write_as_root(ctx, str(destination), template.replace("@CODENAME@", codename)):
        return False
    ctx.track(f"FILE_CREATED:{destination}")
    return True


def remove_stale_rendered_source(ctx: SystemContext, name: str, sources_dir: Path) -> None:
    path = sources_dir / f"{name}.sources"
    if path.is_file() and RENDERED_MARKER in path.read_text():
        ctx.t.logger.info(f"Removing deselected apt source: {name}")
        ctx.t.run(["sudo", "rm", "-f", str(path)])


TEMPLATED_SOURCES = (
    ("docker", "docker-ce", False),
    ("pgadmin4", "pgadmin4", True),
    ("postgresql", "postgresql", True),
    ("teleport", "teleport", True),
)


def generate_templated_apt_sources(ctx: SystemContext, sources_dir: Path, os_release: Path) -> bool:
    selected = {name: _selected(ctx, package, prefix) for name, package, prefix in TEMPLATED_SOURCES}
    for name, wanted in selected.items():
        if not wanted:
            remove_stale_rendered_source(ctx, name, sources_dir)
    if not any(selected.values()):
        return True
    codename = detect_ubuntu_codename(ctx, os_release)
    return all(render_apt_template(ctx, name, codename, sources_dir) for name, wanted in selected.items() if wanted)


def _dry_run_summary(ctx: SystemContext) -> None:
    t = ctx.t
    dry_run_all(t, "Would stow 'apt' package to / (includes third-party repo sources)",
                "Would handle any stow conflicts by backing up existing files")
    for name, package, prefix in TEMPLATED_SOURCES:
        if _selected(ctx, package, prefix):
            dry_run_all(t, f"Would generate /etc/apt/sources.list.d/{name}.sources for the detected Ubuntu codename")
    t.logger.success("Apt sources configured (dry-run).")


def configure_apt_sources(
    ctx: SystemContext,
    sources_dir: Path = Path("/etc/apt/sources.list.d"),
    os_release: Path = Path("/etc/os-release"),
) -> bool:
    t = ctx.t
    t.logger.step("Step 3: Configuring third-party apt sources...")
    creating = not dry_run_all(t, "Would create directories for GPG keys and debsig policies")
    if creating and t.run(["sudo", "mkdir", "-p", *DIRECTORIES]).returncode != 0:
        return False
    if not (download_apt_gpg_keys(ctx) and configure_apt_ppas(ctx)):
        return False
    if t.logger.dry_run:
        _dry_run_summary(ctx)
        return True
    if not (stow_apt_source_files(ctx) and generate_templated_apt_sources(ctx, sources_dir, os_release)):
        return False
    t.logger.success("Apt sources configured.")
    return True
