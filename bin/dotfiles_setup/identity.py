"""First-run git identity setup: writes ~/.gitconfig.local (included
unconditionally from the repo's identity-free git/.gitconfig, Task 11) so a
stranger's fork never inherits your name/email, and prompts only once.

When the private overlay (see overlay.py) provides `git/gitconfig.local`,
~/.gitconfig.local is symlinked to it and the prompt is skipped, including
under `force`."""
from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path

GITCONFIG_LOCAL = Path.home() / ".gitconfig.local"


def _overlay_identity_path(overlay_root: Path | None) -> Path | None:
    if overlay_root is None:
        return None
    candidate = overlay_root / "git" / "gitconfig.local"
    return candidate if candidate.is_file() else None


def _symlink_to_overlay(gitconfig_local: Path, overlay_identity: Path) -> Path:
    if gitconfig_local.is_symlink() and gitconfig_local.resolve() == overlay_identity.resolve():
        return gitconfig_local
    gitconfig_local.parent.mkdir(parents=True, exist_ok=True)
    if gitconfig_local.is_symlink() or gitconfig_local.exists():
        gitconfig_local.unlink()
    os.symlink(overlay_identity, gitconfig_local)
    return gitconfig_local


def ensure_git_identity(
    gitconfig_local: Path | None = None,
    prompt: Callable[[str], str] = input,
    force: bool = False,
    overlay_root: Path | None = None,
) -> Path:
    # Same def-time-binding trap as state.py's STATE_FILE default: resolve
    # the module constant in the body so a monkeypatched GITCONFIG_LOCAL is
    # honored by callers (like cli.py) that don't pass this explicitly.
    gitconfig_local = gitconfig_local if gitconfig_local is not None else GITCONFIG_LOCAL
    overlay_identity = _overlay_identity_path(overlay_root)
    if overlay_identity is not None:
        return _symlink_to_overlay(gitconfig_local, overlay_identity)
    if gitconfig_local.is_file() and not force:
        return gitconfig_local
    name = prompt("Git user.name: ").strip()
    email = prompt("Git user.email: ").strip()
    signing_key = prompt("SSH signing key path (blank to skip commit signing): ").strip()
    gitconfig_local.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"[user]\n\tname = {name}\n\temail = {email}\n"]
    if signing_key:
        lines.append(f"\tsigningkey = {signing_key}\n")
        lines.append("[commit]\n\tgpgsign = true\n[gpg]\n\tformat = ssh\n")
    gitconfig_local.write_text("".join(lines))
    return gitconfig_local
