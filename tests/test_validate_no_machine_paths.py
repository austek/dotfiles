import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "validate-no-machine-paths.sh"
HOME_PATH = "export PATH=/" + "home" + "/someone/bin:$PATH\n"  # split so this file passes the guard it tests


def _git(repo, *args):
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


def _validate(repo, *flags):
    return subprocess.run([str(SCRIPT), *flags], check=False, cwd=repo, capture_output=True, text=True)


@pytest.fixture
def repo(tmp_path):
    _git(tmp_path, "init", "-q")
    (tmp_path / "tracked.txt").write_text("clean\n")
    _git(tmp_path, "add", "tracked.txt")
    _git(tmp_path, "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false", "commit", "-qm", "init")
    return tmp_path


def test_default_mode_ignores_untracked_file_with_home_path(repo):
    (repo / "new.sh").write_text(HOME_PATH)
    assert _validate(repo).returncode == 0


def test_staged_mode_passes_before_add_and_fails_after_add(repo):
    (repo / "new.sh").write_text(HOME_PATH)
    assert _validate(repo, "--staged").returncode == 0
    _git(repo, "add", "new.sh")
    result = _validate(repo, "--staged")
    assert result.returncode == 1
    assert "new.sh" in result.stdout


def test_staged_mode_passes_when_staged_files_are_clean(repo):
    (repo / "new.sh").write_text("echo $HOME\n")
    _git(repo, "add", "new.sh")
    assert _validate(repo, "--staged").returncode == 0


def test_default_mode_fails_on_tracked_file_with_home_path(repo):
    (repo / "tracked.txt").write_text(HOME_PATH)
    assert _validate(repo).returncode == 1


def test_unknown_flag_is_rejected(repo):
    assert _validate(repo, "--bogus").returncode == 2
