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


def test_pre_commit_hook_can_be_committed_itself(tmp_path):
    assert _run_hook(tmp_path, _HOOK.read_text()).returncode == 0
