"""Compiles the xterm-ghostty terminfo entry into `~/.terminfo` on a host that lacks it, so tmux and claude start over ssh from Ghostty."""
from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

from dotfiles_setup.rollback import RollbackLog
from dotfiles_setup.tooling import COMMAND_NOT_FOUND, Tooling, dry_run_all

ENTRY = "xterm-ghostty"
SOURCE_RELATIVE = Path("terminfo") / "xterm-ghostty.terminfo"


def _resolves(t: Tooling) -> bool:
    return t.run(["infocmp", "-x", ENTRY], capture_output=True, text=True).returncode == 0


def pending(t: Tooling) -> tuple[str, ...]:
    """What the step would do: compile the entry when it does not resolve and `tic` is available. Read-only."""
    if shutil.which("tic") is None or _resolves(t):
        return ()
    return (f"install {ENTRY} terminfo into {t.home / '.terminfo'}",)


def _track_install(changes: RollbackLog, installed: Path, made: list[Path]) -> None:
    for directory in made:
        changes.track(f"DIR_CREATED:{directory}", dry_run=False)
    if installed.is_file():
        digest = hashlib.sha256(installed.read_bytes()).hexdigest()
        changes.track(f"TERMINFO_INSTALLED:{installed}|{digest}", dry_run=False)


def _compile(t: Tooling, source: Path, changes: RollbackLog | None) -> None:
    target = t.home / ".terminfo"
    installed = target / "x" / ENTRY
    made = [d for d in (target, target / "x") if not d.exists()]
    done = t.run(["tic", "-x", "-o", str(target), str(source)], capture_output=True, text=True)
    if done.returncode == COMMAND_NOT_FOUND:
        t.logger.warn(f"`tic` is not installed; `TERM={ENTRY}` stays unknown on this host.")
    elif done.returncode != 0:
        t.logger.warn(f"Could not compile {source}; `TERM={ENTRY}` stays unknown on this host.")
    else:
        if changes is not None:
            _track_install(changes, installed, made)
        t.logger.info(f"Installed the {ENTRY} terminfo entry into {target}.")


def install_ghostty_terminfo(t: Tooling, source: Path, changes: RollbackLog | None = None) -> bool:
    """Compiles `source` into `~/.terminfo` only when `infocmp` cannot resolve the entry; never fails the step."""
    if _resolves(t):
        return True
    if dry_run_all(t, f"Would install the {ENTRY} terminfo entry into {t.home / '.terminfo'}"):
        return True
    _compile(t, source, changes)
    return True
