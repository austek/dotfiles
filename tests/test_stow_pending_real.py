import os
import shutil
import subprocess
from pathlib import Path

import pytest
from dotfiles_setup import stow
from dotfiles_setup.log import Logger
from dotfiles_setup.rollback import RollbackLog
from dotfiles_setup.tooling import Tooling

IGNORE_TEXT = "# comment\n  # indented comment\n\\.tmp$ # trailing # more\ncachedir\nfoo#bar\n  spaced  \n^/cache$\n"
FILES = [
    ".zshrc",
    "README.md",
    "notes~",
    "plain.tmp",
    "foo#bar",
    "foo#baz",
    "spaced",
    ".config/app/conf",
    ".config/app/skip.tmp",
    ".config/cachedir/x",
    ".config/cachedir/deep/y",
    ".config/other/README.md",
    "cache/item",
    "cache/deep/item",
    "cache2/item",
    "sibling/item",
]


def _case(tmp_path: Path, index: int, rel: str) -> tuple[Path, Path]:
    base = tmp_path / f"case{index}"
    home, repo = base / "home", base / "repo"
    pkg = repo / "p"
    for path, text in ((pkg / rel, rel), (pkg / ".stow-local-ignore", IGNORE_TEXT)):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    (home / Path(rel).parent).mkdir(parents=True)
    (repo / ".stow-packages").write_text("p\n")
    return home, repo


def _stow_links(home: Path, repo: Path) -> bool:
    env = {**os.environ, "HOME": str(home)}
    cmd = ["stow", "-n", "-v", f"--target={home}", f"--dir={repo}", "p"]
    out = subprocess.run(cmd, capture_output=True, text=True, env=env, check=True, cwd=repo)
    return any(line.startswith("LINK:") for line in (out.stdout + out.stderr).splitlines())


def _pending(home: Path, repo: Path) -> bool:
    plan = stow.StowPlan(Tooling(Logger(dry_run=False), home), repo, None, False, repo / "bk", "s", RollbackLog(repo / "log"), "work")
    return bool(stow.pending_links(plan))


@pytest.mark.skipif(shutil.which("stow") is None, reason="stow is not installed")
@pytest.mark.parametrize("index,rel", list(enumerate(FILES)))
def test_pending_links_agrees_with_stow_about_each_file(tmp_path, index, rel):
    home, repo = _case(tmp_path, index, rel)
    assert _pending(home, repo) == _stow_links(home, repo), rel
