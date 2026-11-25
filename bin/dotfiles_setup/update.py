"""Fast-forwards the dotfiles checkout before an install so presets and packages are current."""
from __future__ import annotations

import os
import shlex
import subprocess
import sys
from pathlib import Path

from dotfiles_setup.log import Logger

_REPO_LOCATION_VARS = (
    "GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR",
    "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_NAMESPACE", "GIT_PREFIX",
)


def _scrubbed_env() -> dict[str, str]:
    return {k: v for k, v in os.environ.items() if k not in _REPO_LOCATION_VARS}


def _git(repo: Path, *args: str, run=subprocess.run) -> subprocess.CompletedProcess:
    return run(["git", "-C", str(repo), *args], capture_output=True, text=True, env=_scrubbed_env())


def _behind_count(repo: Path, run) -> int | None:
    result = _git(repo, "rev-list", "--count", "HEAD..@{u}", run=run)
    return int(result.stdout) if result.returncode == 0 else None


def _no_upstream_message(repo: Path, label: str, run) -> str:
    branch = _git(repo, "symbolic-ref", "--short", "-q", "HEAD", run=run).stdout.strip()
    if not branch:
        return f"Skipping {label} update: HEAD is detached, so there is no upstream to compare with."
    return f"Skipping {label} update: branch '{branch}' has no upstream. Set one with `git push -u origin {shlex.quote(branch)}`."


def pull_if_behind(repo: Path, logger: Logger, run=subprocess.run, label: str = "dotfiles") -> bool:
    """Fetches upstream and fast-forwards when behind; returns True if it pulled. Never fails the install."""
    try:
        fetched = _git(repo, "fetch", "--quiet", run=run)
    except FileNotFoundError:
        logger.warn(f"git is not installed; skipping {label} update.")
        return False
    if fetched.returncode != 0:
        logger.warn(f"Could not fetch {label} updates; continuing with the current checkout.")
        return False
    behind = _behind_count(repo, run)
    if behind is None:
        logger.warn(_no_upstream_message(repo, label, run))
        return False
    if behind == 0:
        return False
    if logger.dry_run_notice(f"Would pull {behind} new {label} commit(s)."):
        return False
    pulled = _git(repo, "pull", "--ff-only", "--quiet", run=run)
    if pulled.returncode != 0:
        logger.warn(f"Could not fast-forward {label} ({behind} new commit(s)): {pulled.stderr.strip()}")
        return False
    logger.info(f"Pulled {behind} new {label} commit(s).")
    return True


RESTARTED_VAR = "DFCTL_RESTARTED_AFTER_PULL"
_ENTRY_NAMES = ("dfctl", "dotfiles-setup")


def restart_if_updated(pulled: bool, logger: Logger, argv: list[str] | None = None, execv=os.execv) -> None:
    """Re-runs the same command after a pull so the new code runs, not the modules already imported."""
    args = sys.argv if argv is None else argv
    if not pulled or os.environ.get(RESTARTED_VAR) or Path(args[0]).name not in _ENTRY_NAMES:
        return
    logger.info("Restarting dfctl to run the pulled code.")
    os.environ[RESTARTED_VAR] = "1"
    execv(sys.executable, [sys.executable, *args])


def pull_overlay_if_git(overlay_root: Path | None, logger: Logger, run=subprocess.run) -> bool:
    """Pulls the overlay when it is a git checkout; a bare local overlay directory is left alone."""
    if overlay_root is None or not (overlay_root / ".git").exists():
        return False
    return pull_if_behind(overlay_root, logger, run=run, label="dotfiles-overlay")
