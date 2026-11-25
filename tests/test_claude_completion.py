import os
import pty
import re
import select
import shlex
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
COMPLETIONS = ROOT / "omz" / ".oh-my-zsh" / "custom" / "completions"
FUNCTIONS = ROOT / "zsh" / ".config" / "zsh" / "functions"
ANSI = re.compile(r"\x1b\[[0-9;?]*[a-zA-Z]|\x1b\][^\x07]*\x07|\x07")

ZSH = shutil.which("zsh")

pytestmark = pytest.mark.skipif(ZSH is None, reason="zsh not installed")


def _drain(fd: int, quiet: float) -> str:
    chunks: list[bytes] = []
    while select.select([fd], [], [], quiet)[0]:
        data = os.read(fd, 65536)
        if not data:
            break
        chunks.append(data)
    return ANSI.sub("", b"".join(chunks).decode(errors="replace"))


def _shell(tmp_path: Path) -> tuple[subprocess.Popen, int]:
    home = tmp_path / "home"
    for account in ("work", "burst"):
        (home / f".claude-{account}").mkdir(parents=True, exist_ok=True)
    env = {"HOME": str(home), "TERM": "dumb", "PATH": "/usr/bin:/bin"}
    master, slave = pty.openpty()
    proc = subprocess.Popen(
        [ZSH or "zsh", "-f"],
        stdin=slave,
        stdout=slave,
        stderr=slave,
        env=env,
        cwd=home,
        close_fds=True,
    )
    os.close(slave)
    fpath = f"{shlex.quote(str(COMPLETIONS))} {shlex.quote(str(FUNCTIONS))}"
    setup = (
        f"fpath=({fpath} $fpath); autoload -Uz compinit _claude_with_names; "
        f"compinit -u -d {shlex.quote(str(tmp_path / 'zcompdump'))}; PS1='> '\n"
    )
    os.write(master, setup.encode())
    _drain(master, 2.0)
    return proc, master


def tab(tmp_path: Path, line: str) -> str:
    proc, master = _shell(tmp_path)
    try:
        os.write(master, f"{line}\t".encode())
        return _drain(master, 3.0)
    finally:
        proc.kill()
        proc.wait()
        os.close(master)


@pytest.mark.parametrize("line", ["claude --account=", "claude --account "])
def test_account_values_are_offered(tmp_path, line):
    out = tab(tmp_path, line)
    assert all(name in out for name in ("main", "work", "burst"))


@pytest.mark.parametrize("line", ["claude --with=", "claude --with "])
def test_with_names_are_offered(tmp_path, line):
    out = tab(tmp_path, line)
    assert all(name in out for name in ("idea", "sonarqube", "grafana"))


def test_with_continues_after_a_comma(tmp_path):
    assert "sonarqube" in tab(tmp_path, "claude --with=idea,")


@pytest.mark.parametrize(
    ("prefix", "completed"),
    [("--acc", "--account="), ("--bur", "--burst "), ("--wit", "--with=")],
)
def test_wrapper_flag_names_complete(tmp_path, prefix, completed):
    assert tab(tmp_path, f"claude {prefix}").endswith(f"claude {completed}")


def test_valued_flags_complete_without_a_trailing_space(tmp_path):
    assert not tab(tmp_path, "claude --acc").endswith(" ")


def test_account_names_follow_an_equals_sign_that_has_a_space_after_it(tmp_path):
    out = tab(tmp_path, "claude --account= ")
    assert all(name in out for name in ("main", "work", "burst"))


def test_account_value_does_not_fall_back_to_files(tmp_path):
    (tmp_path / "home" / "pyproject.toml").parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / "home" / "pyproject.toml").write_text("")
    assert "pyproject.toml" not in tab(tmp_path, "claude --account=")
