"""Commit and push any dotfiles changes. Port of bin/backup.sh.

The original has no `set -e`: a failing git commit/push does not abort the
script, it still prints the completion banner and exits 0. Only the three
explicit checks below (flaky-it sync, machine-path validation, claude settings)
gate."""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


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
        description="Commit and push any dotfiles changes.",
        epilog="Examples:\n  dotfiles-backup save\n",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", metavar="command")
    sub.add_parser("save", help="stage, commit, and push dotfiles changes")
    return parser


def main(argv: list[str] | None = None, run=subprocess.run) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        return 1

    if args.command == "save":
        return _run_save(run=run)

    return 1


def _run_save(run=subprocess.run) -> int:
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

    run(["git", "add", "."], cwd=dotfiles_dir)
    run(
        ["git", "commit", "-m", "chore: update configs and package lists"],
        cwd=dotfiles_dir,
    )
    run(["git", "push"], cwd=dotfiles_dir)

    print("Dotfiles backup complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
