from pathlib import Path

from dotfiles_setup import worktree


def test_a_git_file_marks_a_linked_worktree(tmp_path: Path):
    (tmp_path / ".git").write_text("gitdir: /elsewhere/.git/worktrees/x\n")
    assert worktree.is_linked_worktree(tmp_path) is True


def test_a_git_directory_marks_a_main_checkout(tmp_path: Path):
    (tmp_path / ".git").mkdir()
    assert worktree.is_linked_worktree(tmp_path) is False


def test_a_directory_without_git_is_not_a_linked_worktree(tmp_path: Path):
    assert worktree.is_linked_worktree(tmp_path) is False


def test_a_directory_without_git_lacks_a_git_dir(tmp_path: Path):
    assert worktree.lacks_git_dir(tmp_path) is True


def test_a_git_directory_is_not_lacking(tmp_path: Path):
    (tmp_path / ".git").mkdir()
    assert worktree.lacks_git_dir(tmp_path) is False


def test_a_git_file_lacks_a_git_dir(tmp_path: Path):
    (tmp_path / ".git").write_text("gitdir: /elsewhere/.git/worktrees/x\n")
    assert worktree.lacks_git_dir(tmp_path) is True
