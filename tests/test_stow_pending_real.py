import os
import shutil
import subprocess
from pathlib import Path

import pytest
from dotfiles_setup import stow
from dotfiles_setup.log import Logger
from dotfiles_setup.rollback import RollbackLog
from dotfiles_setup.tooling import Tooling

pytestmark = pytest.mark.skipif(shutil.which("stow") is None, reason="stow is not installed")

IGNORE_TEXT = ".*\\.tmp # trailing # more\ncachedir\n^/cache$\n"
FILES = [".zshrc", "README.md", "plain.tmp", ".config/app/conf", ".config/cachedir/x", "cache/item", "kept/item"]


def _world(tmp_path: Path, files=FILES) -> stow.StowPlan:
    home, repo = tmp_path / "home", tmp_path / "repo"
    home.mkdir()
    for rel in (*files, ".stow-local-ignore"):
        path = repo / "p" / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(IGNORE_TEXT if rel == ".stow-local-ignore" else rel)
    (repo / ".stow-packages").write_text("p\n")
    return stow.StowPlan(Tooling(Logger(dry_run=False), home), repo, None, False, tmp_path / "bk", "s", RollbackLog(tmp_path / "log"), "work")


def _apply(plan: stow.StowPlan) -> None:
    env = {**os.environ, "HOME": str(plan.t.home)}
    cmd = ["stow", "--restow", "--no-folding", f"--target={plan.t.home}", f"--dir={plan.dotfiles_dir}", "p"]
    subprocess.run(cmd, check=True, capture_output=True, env=env, cwd=plan.dotfiles_dir)


def test_a_package_stow_has_not_linked_is_pending(tmp_path, monkeypatch):
    plan = _world(tmp_path)
    monkeypatch.setenv("HOME", str(plan.t.home))
    assert stow.pending_links(plan) == ("link p",)


def test_nothing_is_pending_once_stow_has_applied_the_package(tmp_path, monkeypatch):
    plan = _world(tmp_path)
    monkeypatch.setenv("HOME", str(plan.t.home))
    _apply(plan)
    assert stow.pending_links(plan) == ()


def test_a_file_added_after_the_apply_is_pending_and_an_ignored_one_is_not(tmp_path, monkeypatch):
    plan = _world(tmp_path)
    monkeypatch.setenv("HOME", str(plan.t.home))
    _apply(plan)
    (plan.dotfiles_dir / "p" / "later.tmp").write_text("")
    assert stow.pending_links(plan) == ()
    (plan.dotfiles_dir / "p" / "later").write_text("")
    assert stow.pending_links(plan) == ("link p",)


def test_a_stowrc_in_the_package_root_applies_to_the_dry_run_as_to_the_apply(tmp_path, monkeypatch):
    plan = _world(tmp_path, files=[".zshrc", "secret"])
    monkeypatch.setenv("HOME", str(plan.t.home))
    monkeypatch.chdir(tmp_path)
    (plan.dotfiles_dir / ".stowrc").write_text("--ignore=secret\n")
    _apply(plan)
    assert stow.pending_links(plan) == ()
