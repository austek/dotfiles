"""Commit dotfiles changes to a branch and open a pull request.

`save` never pushes to main. It stays on the backup branch afterwards: the stowed config files are symlinks into this
checkout, so switching back to main would revert the live config until the PR
merges."""
from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import datetime
from pathlib import Path

DEFAULT_BRANCH = "main"


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def claude_settings_changed(dotfiles_dir: Path, run=subprocess.run) -> bool:
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


def main(argv: list[str] | None = None, run=subprocess.run, now=datetime.now) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        return 1

    if args.command == "save":
        return _run_save(run=run, now=now)

    return 1


def _run_save(run=subprocess.run, now=datetime.now) -> int:
    dotfiles_dir = repo_root()

    sync_result = run(
        [str(dotfiles_dir / "bin" / "sync-hunt-flaky-it.sh")], cwd=dotfiles_dir
    )
    if sync_result.returncode != 0:
        return 1

    validate_result = run(
        [str(dotfiles_dir / "scripts" / "validate-no-machine-paths.sh")],
        cwd=dotfiles_dir,
    )
    if validate_result.returncode != 0:
        print(
            "Aborting: fix the paths listed above before committing.",
            file=sys.stderr,
        )
        return 1

    if claude_settings_changed(dotfiles_dir, run=run):
        print(
            "Aborting: claude/.claude/settings.json has uncommitted changes.\n"
            "Run `claude` and invoke /claude-settings-split to move profile-specific\n"
            "changes to claude-profiles/claude_*.json before backing up.",
            file=sys.stderr,
        )
        return 1

    if not _has_changes(dotfiles_dir, run=run):
        print("Nothing to back up.")
        return 0

    branch = _backup_branch(dotfiles_dir, run=run, now=now)
    if branch is None:
        return 1

    steps = [
        ["git", "add", "."],
        ["git", "commit", "-m", "chore: update configs and package lists"],
        ["git", "push", "-u", "origin", branch],
    ]
    if run(["gh", "pr", "view", branch], cwd=dotfiles_dir, capture_output=True).returncode != 0:
        steps.append(["gh", "pr", "create", "--base", DEFAULT_BRANCH, "--fill"])
    for step in steps:
        if run(step, cwd=dotfiles_dir).returncode != 0:
            print(f"Aborting: `{' '.join(step[:2])}` failed.", file=sys.stderr)
            return 1

    print(f"Dotfiles backup complete. After the PR merges: git switch {DEFAULT_BRANCH} && git pull")
    return 0


def _has_changes(dotfiles_dir: Path, run=subprocess.run) -> bool:
    result = run(
        ["git", "status", "--porcelain"],
        cwd=dotfiles_dir,
        capture_output=True,
        text=True,
    )
    return bool((result.stdout or "").strip())


def _backup_branch(dotfiles_dir: Path, run=subprocess.run, now=datetime.now) -> str | None:
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
