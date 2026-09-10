"""First-run git identity setup: writes ~/.gitconfig.local (included
unconditionally from the repo's identity-free git/.gitconfig, Task 11) so a
stranger's fork never inherits your name/email, and prompts only once."""
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

GITCONFIG_LOCAL = Path.home() / ".gitconfig.local"


def ensure_git_identity(
    gitconfig_local: Path | None = None,
    prompt: Callable[[str], str] = input,
    force: bool = False,
) -> Path:
    # Same def-time-binding trap as state.py's STATE_FILE default: resolve
    # the module constant in the body so a monkeypatched GITCONFIG_LOCAL is
    # honored by callers (like cli.py) that don't pass this explicitly.
    gitconfig_local = gitconfig_local if gitconfig_local is not None else GITCONFIG_LOCAL
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
