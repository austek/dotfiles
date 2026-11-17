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


def test_every_work_include_reads_the_overlay_path_and_still_the_legacy_one():
    paths = _include_paths()
    assert len(paths) == 3
    for values in paths.values():
        assert values == ["~/.dotfiles-overlay/git/gitconfig-work", "~/.dotfiles-private/git/gitconfig-work"]
