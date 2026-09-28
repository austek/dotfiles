"""Fast-forwards the dotfiles checkout before an install so presets and packages are current."""
from __future__ import annotations

import os
import subprocess
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


def pull_if_behind(repo: Path, logger: Logger, run=subprocess.run) -> bool:
    """Fetches upstream and fast-forwards when behind; returns True if it pulled. Never fails the install."""
    try:
        fetched = _git(repo, "fetch", "--quiet", run=run)
    except FileNotFoundError:
        logger.warn("git is not installed; skipping dotfiles update.")
        return False
    if fetched.returncode != 0:
        logger.warn("Could not fetch dotfiles updates; continuing with the current checkout.")
        return False
    behind = _behind_count(repo, run)
    if behind is None:
        logger.warn("Could not determine the dotfiles upstream; continuing with the current checkout.")
        return False
    if behind == 0:
        return False
    if logger.dry_run_notice(f"Would pull {behind} new dotfiles commit(s)."):
        return False
    pulled = _git(repo, "pull", "--ff-only", "--quiet", run=run)
    if pulled.returncode != 0:
        logger.warn(f"Could not fast-forward dotfiles ({behind} new commit(s)): {pulled.stderr.strip()}")
        return False
    logger.info(f"Pulled {behind} new dotfiles commit(s).")
    return True
