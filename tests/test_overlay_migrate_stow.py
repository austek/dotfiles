import os
import shutil
import subprocess
from pathlib import Path

import pytest
from dotfiles_setup import overlay, overlay_migrate, rollback, tools
from dotfiles_setup.log import Logger
from dotfiles_setup.rollback import RollbackLog

pytestmark = pytest.mark.skipif(
    shutil.which("stow") is None or shutil.which("git") is None, reason="stow or git not installed"
)


def _stow(root: Path, home: Path, *args: str) -> None:
    subprocess.run(["stow", "--no-folding", f"--target={home}", *args], cwd=root, check=True, capture_output=True)


def _git(*args: str, cwd: Path | None = None) -> str:
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
    return subprocess.run(["git", *args], cwd=cwd, env=env, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def stowed_overlay(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    legacy, new = home / ".dotfiles-private", home / ".dotfiles-overlay"
    monkeypatch.setattr(overlay, "LEGACY_OVERLAY_ROOT", legacy)
    monkeypatch.setattr(overlay, "DEFAULT_OVERLAY_ROOT", new)
    (legacy / "zsh/.config/zsh/claude-with.d").mkdir(parents=True)
    (legacy / "zsh/.config/zsh/claude-with.d/chip.zsh").write_text("chip")
    (legacy / "claude/.claude").mkdir(parents=True)
    (legacy / "claude/.claude/CLAUDE.md").write_text("rules")
    (legacy / ".stow-packages").write_text("zsh\nclaude\n")
    _stow(legacy, home, "zsh", "claude")
    return home, legacy, new


def _tooling(home: Path) -> tools.Tooling:
    return tools.Tooling(Logger(dry_run=False, verbosity=1), home)


def _migrate(home: Path) -> bool:
    return overlay_migrate.migrate_legacy_overlay(_tooling(home), RollbackLog(home / "rollback.log"))


def test_the_migration_leaves_every_link_working_from_the_new_path(stowed_overlay):
    home, legacy, new = stowed_overlay
    link = home / ".config/zsh/claude-with.d/chip.zsh"
    assert link.is_symlink()
    assert ".dotfiles-private" in os.readlink(link)

    assert _migrate(home)

    assert not legacy.exists()
    assert link.read_text() == "chip"
    assert ".dotfiles-overlay" in os.readlink(link)
    assert ".dotfiles-private" not in os.readlink(link)
    assert (home / ".claude/CLAUDE.md").resolve() == (new / "claude/.claude/CLAUDE.md").resolve()


def test_a_listed_package_without_a_directory_does_not_stop_the_migration(stowed_overlay):
    home, legacy, _ = stowed_overlay
    (legacy / ".stow-packages").write_text("zsh\nclaude\nnot-there\n")
    assert _migrate(home)
    assert (home / ".config/zsh/claude-with.d/chip.zsh").read_text() == "chip"


def test_a_bare_move_would_leave_dangling_links_that_stow_refuses(stowed_overlay):
    home, legacy, new = stowed_overlay
    legacy.rename(new)
    result = subprocess.run(
        ["stow", "--no-folding", f"--target={home}", "zsh"], cwd=new, capture_output=True, text=True, check=False
    )
    assert result.returncode != 0


def test_linked_git_worktrees_keep_working_after_the_move(stowed_overlay, tmp_path):
    home, legacy, new = stowed_overlay
    _git("init", "-q", ".", cwd=legacy)
    _git("add", ".", cwd=legacy)
    _git("commit", "-q", "-m", "init", cwd=legacy)
    worktree = tmp_path / "overlay-wt"
    _git("worktree", "add", "-q", str(worktree), "-b", "feature", cwd=legacy)
    assert _git("rev-parse", "--show-toplevel", cwd=worktree) == str(worktree)

    assert _migrate(home)

    assert _git("rev-parse", "--show-toplevel", cwd=worktree) == str(worktree)
    assert str(new) in (worktree / ".git").read_text()


def test_rolling_back_the_move_relinks_everything_from_the_old_path(stowed_overlay):
    home, legacy, new = stowed_overlay
    (home / ".gitconfig.local").symlink_to(legacy / "git" / "gitconfig.local")
    log = RollbackLog(home / "rollback.log")
    assert overlay_migrate.migrate_legacy_overlay(_tooling(home), log)

    rollback._undo(rollback.RollbackContext(_tooling(home), log, home / "dotfiles", new), log.entries()[0])

    link = home / ".config/zsh/claude-with.d/chip.zsh"
    assert not new.exists()
    assert link.read_text() == "chip"
    assert ".dotfiles-private" in os.readlink(link)
    assert os.readlink(home / ".gitconfig.local") == str(legacy / "git" / "gitconfig.local")
