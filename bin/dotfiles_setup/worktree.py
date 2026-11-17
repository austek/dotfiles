"""Detects a linked git worktree, which stow and `propose` must not treat as a dotfiles checkout."""
from __future__ import annotations

from pathlib import Path


def is_linked_worktree(root: Path) -> bool:
    """True when `.git` is a file, as in a linked worktree or a submodule; a main checkout has a `.git` directory."""
    return (root / ".git").is_file()


def lacks_git_dir(root: Path) -> bool:
    """True when `root` has no `.git` directory; git would then resolve to an enclosing repository."""
    return not (root / ".git").is_dir()
