"""Commit dotfiles changes to a branch and open a pull request.

`save` also backs up the private overlay when it is a separate git repo.
`save` never pushes to main. It stays on the backup branch because stowed configs symlink into this checkout."""
from __future__ import annotations

import argparse
import subprocess
import sys
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from dotfiles_setup.overlay import find_overlay_root
from git_ops import (
    RunFn,
    claude_settings_changed,
    create_branch,
    current_branch,
    has_changes,
    in_worktree,
    pr_exists,
    status_failed,
    untracked_files,
)

DEFAULT_BRANCH = "main"
COMMIT_MESSAGE = "chore: update configs and package lists NO_ISSUE"
VALIDATE_SCRIPT = Path("scripts") / "validate-no-machine-paths.sh"
UNTRACKED_LIST_CAP = 50
__all__ = ["DEFAULT_BRANCH", "RunFn", "claude_settings_changed", "main"]


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="dotfiles-backup",
        description="Commit dotfiles changes to a branch and open a pull request. Run it from the main checkout only.",
        epilog="Examples:\n  dotfiles-backup save\n",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", metavar="command")
    sub.add_parser(
        "save",
        help="commit, push the branch (backup/<timestamp> from main), and open a PR if none exists; main checkout only",
    )
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
    validate = run([str(dotfiles_dir / VALIDATE_SCRIPT)], cwd=dotfiles_dir)
    if validate.returncode != 0:
        return "Aborting: fix the paths listed above before committing."
    if claude_settings_changed(dotfiles_dir, run=run):
        return (
            "Aborting: claude/.claude/settings.json has uncommitted changes.\n"
            "Run `claude` and invoke /claude-settings-split to move profile-specific\n"
            "changes to claude-profiles/claude_*.json before backing up."
        )
    return None


def _publish_steps(dotfiles_dir: Path, branch: str, run: RunFn) -> list[list[str]]:
    steps = [
        ["git", "commit", "-m", COMMIT_MESSAGE],
        ["git", "push", "-u", "origin", branch],
    ]
    if not pr_exists(dotfiles_dir, branch, run=run):
        steps.append(["gh", "pr", "create", "--base", DEFAULT_BRANCH, "--fill"])
    return steps


def _print_untracked(untracked: list[str]) -> None:
    if not untracked:
        return
    print(f"New untracked files being added ({len(untracked)}):")
    for name in untracked[:UNTRACKED_LIST_CAP]:
        print(f"  {name}")
    if len(untracked) > UNTRACKED_LIST_CAP:
        print(f"  ... and {len(untracked) - UNTRACKED_LIST_CAP} more")


def _stage(dotfiles_dir: Path, run: RunFn, validate_staged: bool) -> str | None:
    """Stages everything; returns an abort message, or None when staging succeeded."""
    untracked = untracked_files(dotfiles_dir, run=run)
    if run(["git", "add", "."], cwd=dotfiles_dir).returncode != 0:
        run(["git", "reset", "-q"], cwd=dotfiles_dir)
        return "Aborting: `git add` failed."
    if validate_staged and run([str(dotfiles_dir / VALIDATE_SCRIPT), "--staged"], cwd=dotfiles_dir).returncode != 0:
        run(["git", "reset", "-q"], cwd=dotfiles_dir)
        return "Aborting: fix the paths listed above before committing. Nothing was committed."
    _print_untracked(untracked)
    return None


def _private_git_root(public_root: Path) -> Path | None:
    root = find_overlay_root()
    is_separate_repo = root is not None and (root / ".git").exists() and root.resolve() != public_root.resolve()
    return root if is_separate_repo else None


def _run_save(run: RunFn = subprocess.run, now: Callable[[], datetime] = datetime.now) -> int:
    public_root = repo_root()
    codes = [_guarded(public_root, lambda: _save_repo(public_root, run, now, is_public=True))]
    private_root = _private_git_root(public_root)
    if private_root is not None:
        print(f"Backing up private overlay: {private_root}")
        codes.append(_guarded(private_root, lambda: _save_repo(private_root, run, now, is_public=False)))
    return max(codes)


def _guarded(repo: Path, save: Callable[[], int]) -> int:
    try:
        return save()
    except (OSError, subprocess.SubprocessError) as exc:
        return _abort(f"Aborting: backup of {repo} failed: {exc}")


def _early_error(dotfiles_dir: Path, run: RunFn, is_public: bool) -> str | None:
    if in_worktree(dotfiles_dir, run=run):
        return f"Aborting: {dotfiles_dir} is a linked worktree. Run `dotfiles-backup save` from the main checkout."
    preflight = _preflight_error(dotfiles_dir, run) if is_public else None
    if preflight:
        return preflight
    return "Aborting: `git status` failed." if status_failed(dotfiles_dir, run=run) else None


def _save_repo(dotfiles_dir: Path, run: RunFn, now: Callable[[], datetime], is_public: bool) -> int:
    early_error = _early_error(dotfiles_dir, run, is_public)
    if early_error:
        return _abort(early_error)
    if not has_changes(dotfiles_dir, run=run):
        print("Nothing to back up.")
        return 0
    stage_error = _stage(dotfiles_dir, run, validate_staged=is_public)
    if stage_error:
        return _abort(stage_error)
    branch = _backup_branch(dotfiles_dir, run=run, now=now)
    if branch is None:
        run(["git", "reset", "-q"], cwd=dotfiles_dir)
        return 1
    return _publish(dotfiles_dir, branch, run)


def _publish(dotfiles_dir: Path, branch: str, run: RunFn) -> int:
    for step in _publish_steps(dotfiles_dir, branch, run):
        if run(step, cwd=dotfiles_dir).returncode != 0:
            return _abort(f"Aborting: `{' '.join(step[:2])}` failed.")
    print(f"Dotfiles backup complete. After the PR merges: git switch {DEFAULT_BRANCH} && git pull")
    return 0


def _backup_branch(
    dotfiles_dir: Path, run: RunFn = subprocess.run, now: Callable[[], datetime] = datetime.now
) -> str | None:
    branch = current_branch(dotfiles_dir, run=run)
    if branch not in ("", DEFAULT_BRANCH):
        return branch
    branch = f"backup/{now():%Y%m%d-%H%M%S}"
    if not create_branch(dotfiles_dir, branch, run=run):
        print(f"Aborting: cannot create branch {branch}.", file=sys.stderr)
        return None
    return branch


if __name__ == "__main__":
    sys.exit(main())
