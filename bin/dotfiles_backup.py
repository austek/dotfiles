"""Commit dotfiles changes to a branch and open a pull request.

`save` never pushes to main. It stays on the backup branch because stowed configs symlink into this checkout."""
from __future__ import annotations

import argparse
import subprocess
import sys
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

DEFAULT_BRANCH = "main"
RunFn = Callable[..., Any]


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def claude_settings_changed(dotfiles_dir: Path, run: RunFn = subprocess.run) -> bool:
    result = run(
        ["git", "status", "--porcelain", "--", "claude/.claude/settings.json"],
        cwd=dotfiles_dir,
        capture_output=True,
        text=True,
    )
    return bool((result.stdout or "").strip())


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="dotfiles-backup",
        description="Commit dotfiles changes to a branch and open a pull request.",
        epilog="Examples:\n  dotfiles-backup save\n",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", metavar="command")
    sub.add_parser("save", help="commit, push the branch (backup/<timestamp> from main), and open a PR if none exists")
    return parser


def main(
    argv: list[str] | None = None, run: RunFn = subprocess.run, now: Callable[[], datetime] = datetime.now
) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        return 1

    if args.command == "save":
        return _run_save(run=run, now=now)

    return 1


def _abort(message: str) -> int:
    print(message, file=sys.stderr)
    return 1


def _preflight_error(dotfiles_dir: Path, run: RunFn) -> str | None:
    validate = run([str(dotfiles_dir / "scripts" / "validate-no-machine-paths.sh")], cwd=dotfiles_dir)
    if validate.returncode != 0:
        return "Aborting: fix the paths listed above before committing."
    if claude_settings_changed(dotfiles_dir, run=run):
        return (
            "Aborting: claude/.claude/settings.json has uncommitted changes.\n"
            "Run `claude` and invoke /claude-settings-split to move profile-specific\n"
            "changes to claude-profiles/claude_*.json before backing up."
        )
    return None


def _save_steps(dotfiles_dir: Path, branch: str, run: RunFn) -> list[list[str]]:
    steps = [
        ["git", "add", "."],
        ["git", "commit", "-m", "chore: update configs and package lists"],
        ["git", "push", "-u", "origin", branch],
    ]
    if run(["gh", "pr", "view", branch], cwd=dotfiles_dir, capture_output=True).returncode != 0:
        steps.append(["gh", "pr", "create", "--base", DEFAULT_BRANCH, "--fill"])
    return steps


def _run_save(run: RunFn = subprocess.run, now: Callable[[], datetime] = datetime.now) -> int:
    dotfiles_dir = repo_root()
    error = _preflight_error(dotfiles_dir, run)
    if error:
        return _abort(error)
    if not _has_changes(dotfiles_dir, run=run):
        print("Nothing to back up.")
        return 0
    branch = _backup_branch(dotfiles_dir, run=run, now=now)
    if branch is None:
        return 1
    for step in _save_steps(dotfiles_dir, branch, run):
        if run(step, cwd=dotfiles_dir).returncode != 0:
            return _abort(f"Aborting: `{' '.join(step[:2])}` failed.")
    print(f"Dotfiles backup complete. After the PR merges: git switch {DEFAULT_BRANCH} && git pull")
    return 0


def _has_changes(dotfiles_dir: Path, run: RunFn = subprocess.run) -> bool:
    result = run(
        ["git", "status", "--porcelain"],
        cwd=dotfiles_dir,
        capture_output=True,
        text=True,
    )
    return bool((result.stdout or "").strip())


def _backup_branch(
    dotfiles_dir: Path, run: RunFn = subprocess.run, now: Callable[[], datetime] = datetime.now
) -> str | None:
    current = run(
        ["git", "branch", "--show-current"],
        cwd=dotfiles_dir,
        capture_output=True,
        text=True,
    )
    branch = (current.stdout or "").strip()
    if branch not in ("", DEFAULT_BRANCH):
        return branch
    branch = f"backup/{now():%Y%m%d-%H%M%S}"
    if run(["git", "switch", "-c", branch], cwd=dotfiles_dir).returncode != 0:
        print(f"Aborting: cannot create branch {branch}.", file=sys.stderr)
        return None
    return branch


if __name__ == "__main__":
    sys.exit(main())
