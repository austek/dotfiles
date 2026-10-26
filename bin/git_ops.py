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


def claude_settings_changed(repo: Path, run: RunFn = subprocess.run) -> bool:
    return bool(_git_output(repo, ["git", "status", "--porcelain", "--", SETTINGS_PATH], run))


def has_changes(repo: Path, run: RunFn = subprocess.run) -> bool:
    return bool(_git_output(repo, ["git", "status", "--porcelain"], run))


def current_branch(repo: Path, run: RunFn = subprocess.run) -> str:
    return _git_output(repo, ["git", "branch", "--show-current"], run)


def create_branch(repo: Path, branch: str, run: RunFn = subprocess.run) -> bool:
    return run(["git", "switch", "-c", branch], cwd=repo).returncode == 0


def pr_exists(repo: Path, branch: str, run: RunFn = subprocess.run) -> bool:
    return run(["gh", "pr", "view", branch], cwd=repo, capture_output=True).returncode == 0
