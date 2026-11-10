"""Thin git/gh subprocess wrappers; every function takes the runner so tests inject a fake."""
from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

RunFn = Callable[..., Any]
SETTINGS_PATH = "claude/.claude/settings.json"


def _stdout(result: Any) -> str:
    return (result.stdout or "").strip()


def _git_output(repo: Path, argv: list[str], run: RunFn) -> str:
    return _stdout(run(argv, cwd=repo, capture_output=True, text=True))


def _rev_parse(repo: Path, flag: str, run: RunFn, absolute: bool) -> Path | None:
    argv = ["git", "rev-parse", *(["--path-format=absolute"] if absolute else []), flag]
    result = run(argv, cwd=repo, capture_output=True, text=True)
    out = _stdout(result)
    return (repo / out).resolve() if result.returncode == 0 and out else None


def in_worktree(repo: Path, run: RunFn = subprocess.run) -> bool:
    """True in a linked worktree, and when the git dirs cannot be determined."""
    for absolute in (True, False):
        common = _rev_parse(repo, "--git-common-dir", run, absolute)
        git_dir = _rev_parse(repo, "--git-dir", run, absolute)
        if common is not None and git_dir is not None:
            return common != git_dir
    return True


def untracked_files(repo: Path, run: RunFn = subprocess.run) -> list[str]:
    out = _git_output(repo, ["git", "ls-files", "--others", "--exclude-standard"], run)
    return out.splitlines()


def claude_settings_changed(repo: Path, run: RunFn = subprocess.run) -> bool:
    return bool(_git_output(repo, ["git", "status", "--porcelain", "--", SETTINGS_PATH], run))


def status_failed(repo: Path, run: RunFn = subprocess.run) -> bool:
    return run(["git", "status", "--porcelain"], cwd=repo, capture_output=True, text=True).returncode != 0


def has_changes(repo: Path, run: RunFn = subprocess.run) -> bool:
    return bool(_git_output(repo, ["git", "status", "--porcelain"], run))


def current_branch(repo: Path, run: RunFn = subprocess.run) -> str:
    return _git_output(repo, ["git", "branch", "--show-current"], run)


def create_branch(repo: Path, branch: str, run: RunFn = subprocess.run) -> bool:
    return run(["git", "switch", "-c", branch], cwd=repo).returncode == 0


def pr_exists(repo: Path, branch: str, run: RunFn = subprocess.run) -> bool:
    return run(["gh", "pr", "view", branch], cwd=repo, capture_output=True).returncode == 0
