import subprocess
from pathlib import Path

BIN = Path(__file__).resolve().parent.parent / "bin"
NOTICE = "'dotfiles-setup' is deprecated; use 'dfctl'."


def _run(command: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([str(command), *args], capture_output=True, text=True, check=False)


def test_the_old_name_runs_dfctl_and_says_it_is_deprecated():
    result = _run(BIN / "dotfiles-setup", "--help")
    assert result.returncode == 0
    assert NOTICE in result.stderr
    assert result.stdout.startswith("usage: dfctl")


def test_the_old_name_forwards_arguments_and_the_exit_code():
    shim = _run(BIN / "dotfiles-setup", "no-such-command")
    direct = _run(BIN / "dfctl", "no-such-command")
    assert shim.returncode == direct.returncode != 0
    assert shim.stderr.replace(NOTICE + "\n", "") == direct.stderr


def test_the_old_name_works_through_a_symlink(tmp_path):
    link = tmp_path / "dotfiles-setup"
    link.symlink_to(BIN / "dotfiles-setup")
    result = _run(link, "--help")
    assert (result.returncode, NOTICE in result.stderr) == (0, True)
    assert result.stdout.startswith("usage: dfctl")


def test_the_new_name_prints_no_notice():
    assert "deprecated" not in _run(BIN / "dfctl", "--help").stderr
