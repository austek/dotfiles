"""Fast-forwards the dotfiles checkout before an install so presets and packages are current."""
from __future__ import annotations

import subprocess
from pathlib import Path

from dotfiles_setup.log import Logger


def _git(repo: Path, *args: str, run=subprocess.run) -> subprocess.CompletedProcess:
    return run(["git", "-C", str(repo), *args], capture_output=True, text=True)


def _behind_count(repo: Path, run) -> int | None:
    result = _git(repo, "rev-list", "--count", "HEAD..@{u}", run=run)
    return int(result.stdout) if result.returncode == 0 else None


def pull_if_behind(repo: Path, logger: Logger, run=subprocess.run) -> bool:
    """Fetches upstream and fast-forwards when behind; returns True if it pulled. Never fails the install."""
    if _git(repo, "fetch", "--quiet", run=run).returncode != 0:
        logger.warn("Could not fetch dotfiles updates; continuing with the current checkout.")
        return False
    behind = _behind_count(repo, run)
    if not behind:
        return False
    if logger.dry_run_notice(f"Would pull {behind} new dotfiles commit(s)."):
        return False
    pulled = _git(repo, "pull", "--ff-only", "--quiet", run=run)
    if pulled.returncode != 0:
        logger.warn(f"Could not fast-forward dotfiles ({behind} new commit(s)): {pulled.stderr.strip()}")
        return False
    logger.info(f"Pulled {behind} new dotfiles commit(s).")
    return True
