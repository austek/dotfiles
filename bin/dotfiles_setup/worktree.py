"""Detects a linked git worktree, which stow and `propose` must not treat as a dotfiles checkout."""
from __future__ import annotations

from pathlib import Path


def is_linked_worktree(root: Path) -> bool:
    """A linked worktree has a `.git` file pointing at the main checkout; the main checkout has a `.git` directory."""
    return (root / ".git").is_file()
