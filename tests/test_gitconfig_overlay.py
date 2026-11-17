import os
import shutil
import subprocess
from pathlib import Path

import pytest

GITCONFIG = Path(__file__).resolve().parent.parent / "git" / ".gitconfig"

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")


def _include_paths() -> dict[str, list[str]]:
    out = subprocess.run(
        ["git", "config", "--file", str(GITCONFIG), "--get-regexp", r"^includeif\..*\.path$"],
        capture_output=True, text=True, check=True,
    ).stdout
    paths: dict[str, list[str]] = {}
    for line in out.splitlines():
        key, _, value = line.partition(" ")
        paths.setdefault(key, []).append(value)
    return paths


def test_every_work_include_lists_the_legacy_path_before_the_overlay_path():
    paths = _include_paths()
    assert len(paths) == 3
    for values in paths.values():
        assert values == ["~/.dotfiles-private/git/gitconfig-work", "~/.dotfiles-overlay/git/gitconfig-work"]


def _work_email(home: Path, *, legacy: str | None, overlay: str | None) -> str:
    """The user.email git resolves in a repo with a Collibra remote, with the given work configs present."""
    for directory, email in ((".dotfiles-private", legacy), (".dotfiles-overlay", overlay)):
        if email is not None:
            (home / directory / "git").mkdir(parents=True)
            (home / directory / "git" / "gitconfig-work").write_text(f"[user]\n\temail = {email}\n")
    repo = home / "repo"
    repo.mkdir()
    env = {"PATH": os.environ["PATH"], "HOME": str(home), "GIT_CONFIG_GLOBAL": str(GITCONFIG), "GIT_CONFIG_NOSYSTEM": "1"}
    subprocess.run(["git", "init", "-q"], cwd=repo, env=env, check=True)
    subprocess.run(["git", "remote", "add", "origin", "https://github.com/collibra/x.git"], cwd=repo, env=env, check=True)
    result = subprocess.run(["git", "config", "user.email"], cwd=repo, env=env, capture_output=True, text=True, check=False)
    return result.stdout.strip()


def test_the_overlay_identity_wins_when_both_checkouts_exist(tmp_path):
    assert _work_email(tmp_path, legacy="legacy@example.com", overlay="overlay@example.com") == "overlay@example.com"


def test_the_legacy_identity_is_used_while_it_is_the_only_checkout(tmp_path):
    assert _work_email(tmp_path, legacy="legacy@example.com", overlay=None) == "legacy@example.com"


def test_the_overlay_identity_is_used_when_it_is_the_only_checkout(tmp_path):
    assert _work_email(tmp_path, legacy=None, overlay="overlay@example.com") == "overlay@example.com"
