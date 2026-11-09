import os
import subprocess
from pathlib import Path

import pytest

_MARK = "CLAUDE" + "NOTE:"
_HOOK = (
    Path(__file__).resolve().parent.parent / "githooks" / ".git-hooks" / "pre-commit"
)


def _run_hook(tmp_path, content):
    git = lambda *a: subprocess.run(
        ["git", *a], cwd=tmp_path, check=True, capture_output=True
    )
    git("init", "-q")
    (tmp_path / "f.md").write_text(content)
    git("add", "f.md")
    return subprocess.run(
        [str(_HOOK)], cwd=tmp_path, capture_output=True, text=True, check=False
    )


@pytest.mark.parametrize(
    "content",
    [
        f"# {_MARK} fix later\n",
        f"x = 1  # {_MARK} temp\n",
        f"{_MARK} first line\n",
        f"x `{_MARK} unterminated\n",
    ],
)
def test_pre_commit_rejects_leftover_marker(tmp_path, content):
    assert _run_hook(tmp_path, content).returncode == 1


@pytest.mark.parametrize(
    "content",
    [
        f"- prefix `{_MARK}`, strip before commit\n",
        "no marker here\n",
        "CLAUDENOTE without colon\n",
    ],
)
def test_pre_commit_allows_documented_or_absent_marker(tmp_path, content):
    assert _run_hook(tmp_path, content).returncode == 0


def test_pre_commit_rejects_early_marker_in_large_file(tmp_path):
    content = f"# {_MARK} early\n" + "filler line\n" * 20000
    assert _run_hook(tmp_path, content).returncode == 1


def test_pre_commit_chains_to_repo_hook_under_global_hooks_path(tmp_path):
    global_hooks = tmp_path / "global-hooks"
    global_hooks.mkdir()
    (global_hooks / "pre-commit").symlink_to(_HOOK)
    repo = tmp_path / "repo"
    repo.mkdir()
    git = lambda *a: subprocess.run(["git", *a], cwd=repo, check=True, capture_output=True)
    git("init", "-q")
    git("config", "core.hooksPath", str(global_hooks))
    local = repo / ".git" / "hooks" / "pre-commit"
    local.write_text("#!/bin/sh\ntouch chained\n")
    local.chmod(0o755)
    (repo / "f.md").write_text("ok\n")
    git("add", "f.md")
    result = subprocess.run(
        [str(global_hooks / "pre-commit")], cwd=repo, capture_output=True, text=True, check=False, timeout=30
    )
    assert result.returncode == 0
    assert (repo / "chained").exists()


_REPO = Path(__file__).resolve().parent.parent
_GLOBAL_HOOKS = _REPO / "githooks" / ".git-hooks"
_TRAILER = "Co-Authored-By: Claude <noreply@anthropic.com>"


def _repo_with_repo_hooks(tmp_path, global_hooks):
    repo = tmp_path / "repo"
    (repo / ".githooks").mkdir(parents=True)
    (repo / "scripts").mkdir()
    for name in ("pre-commit", "commit-msg"):
        (repo / ".githooks" / name).write_bytes((_REPO / ".githooks" / name).read_bytes())
        (repo / ".githooks" / name).chmod(0o755)
    for name in ("validate-shell.sh", "validate-no-machine-paths.sh"):
        (repo / "scripts" / name).write_text("exit 0\n")
    env = {"HOME": str(tmp_path), "DOTFILES_GLOBAL_HOOKS": str(global_hooks), "PATH": os.environ["PATH"]}
    git = lambda *a, check=True: subprocess.run(
        ["git", *a], cwd=repo, env=env, capture_output=True, text=True, check=check, timeout=60
    )
    git("init", "-q")
    git("config", "user.name", "t")
    git("config", "user.email", "t@example.com")
    git("config", "commit.gpgsign", "false")
    git("config", "core.hooksPath", ".githooks")
    return repo, git


def test_repo_hooks_run_the_global_hooks(tmp_path):
    repo, git = _repo_with_repo_hooks(tmp_path, _GLOBAL_HOOKS)
    (repo / "f.md").write_text(f"# {_MARK} fix later\n")
    git("add", "f.md")
    rejected = git("commit", "-q", "-m", "x", check=False)
    (repo / "f.md").write_text("ok\n")
    git("add", "f.md")
    git("commit", "-q", "-m", f"subject\n\n{_TRAILER}")
    message = git("log", "-n", "1", "--format=%B").stdout
    assert (rejected.returncode, _TRAILER in message) == (1, False)


def test_repo_hooks_skip_missing_global_hooks(tmp_path):
    repo, git = _repo_with_repo_hooks(tmp_path, tmp_path / "absent")
    (repo / "f.md").write_text("ok\n")
    git("add", "f.md")
    git("commit", "-q", "-m", f"subject\n\n{_TRAILER}")
    assert _TRAILER in git("log", "-n", "1", "--format=%B").stdout


def test_repo_hooks_commit_without_home_or_global_hooks_dir(tmp_path):
    repo, git = _repo_with_repo_hooks(tmp_path, tmp_path / "absent")
    env = {"PATH": os.environ["PATH"], "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null"}
    (repo / "f.md").write_text("ok\n")
    git("add", "f.md")
    result = subprocess.run(
        ["git", "commit", "-q", "-m", "x"], cwd=repo, env=env, capture_output=True, text=True, check=False, timeout=60
    )
    assert result.returncode == 0, result.stderr


def test_pre_commit_hook_can_be_committed_itself(tmp_path):
    assert _run_hook(tmp_path, _HOOK.read_text()).returncode == 0
