import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

FUNCTIONS = Path(__file__).resolve().parent.parent / "zsh" / ".config" / "zsh" / "functions"

pytestmark = pytest.mark.skipif(shutil.which("zsh") is None, reason="zsh not installed")


def _stub(bin_dir: Path, name: str, body: str) -> None:
    path = bin_dir / name
    path.write_text(f"#!/bin/sh\n{body}\n")
    path.chmod(0o755)


def _run(tmp_path: Path, script: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    full_env = {
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "HOME": str(tmp_path / "home"),
        "LOG": str(tmp_path / "log"),
        **(env or {}),
    }
    (tmp_path / "home").mkdir(exist_ok=True)
    setup = f"fpath=({FUNCTIONS} $fpath); autoload -Uz claude-with claude-tmux secrets_hydrate bw_unlock\n"
    return subprocess.run(
        ["zsh", "-f", "-c", setup + script], capture_output=True, text=True, env=full_env, timeout=30, check=False
    )


def _log(tmp_path: Path) -> list[str]:
    log = tmp_path / "log"
    return log.read_text().splitlines() if log.exists() else []


def _claude_stub(tmp_path: Path, extra: str = "") -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    _stub(bin_dir, "claude", f'echo "claude $*" >> "$LOG"\n{extra}')


def test_claude_with_enables_then_reverts_on_normal_exit(tmp_path):
    _claude_stub(tmp_path)
    result = _run(tmp_path, "claude-with idea -- --resume")
    assert result.returncode == 0
    lines = _log(tmp_path)
    assert lines[0].startswith("claude mcp add --transport http idea")
    assert lines[1] == "claude --resume"
    assert lines[2] == "claude mcp remove idea -s local"


def test_claude_with_reverts_when_shell_receives_sigterm(tmp_path):
    _claude_stub(tmp_path, 'case "$1" in mcp) ;; *) kill -TERM $PPID; sleep 0.3 ;; esac')
    result = _run(tmp_path, "claude-with idea")
    assert "claude mcp remove idea -s local" in _log(tmp_path)
    assert result.returncode == 143


def test_claude_with_skips_entry_when_secret_missing(tmp_path):
    _claude_stub(tmp_path)
    result = _run(tmp_path, "claude-with coralogix", env={"CORALOGIX_API_KEY": ""})
    assert result.returncode == 1
    assert "$CORALOGIX_API_KEY is not set" in result.stderr
    assert _log(tmp_path) == []


def test_claude_with_rejects_unknown_name(tmp_path):
    _claude_stub(tmp_path)
    result = _run(tmp_path, "claude-with nope")
    assert result.returncode == 1
    assert "no restore entry for 'nope'" in result.stderr


def test_claude_tmux_runs_command_directly_inside_tmux(tmp_path):
    result = _run(tmp_path, "claude-tmux label print -r -- hello", env={"TMUX": "/tmp/x,1,0"})
    assert result.returncode == 0
    assert result.stdout.strip() == "hello"


def test_claude_tmux_runs_command_directly_without_tty(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _stub(bin_dir, "tmux", 'echo tmux >> "$LOG"')
    result = _run(tmp_path, "claude-tmux label print -r -- hello")
    assert result.stdout.strip() == "hello"
    assert _log(tmp_path) == []


@pytest.mark.skipif(shutil.which("jq") is None, reason="jq not installed")
def test_secrets_hydrate_writes_private_key_verbatim_with_mode_600(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _stub(bin_dir, "bw", 'case "$1" in status) echo \'{"status":"unlocked"}\' ;; '
         'get) printf "%s\\n" \'{"sshKey":{"privateKey":"a\\\\tb"}}\' ;; esac')
    _stub(bin_dir, "ssh-keygen", "echo ssh-ed25519 PUB")
    _stub(bin_dir, "ssh-add", "true")
    result = _run(tmp_path, "secrets_hydrate", env={"BW_SESSION": "token"})
    key = tmp_path / "home" / ".ssh" / "id_ed25519"
    assert result.returncode == 0
    assert key.read_text() == "a\\tb\n"
    assert stat.S_IMODE(key.stat().st_mode) == 0o600


@pytest.mark.skipif(shutil.which("jq") is None, reason="jq not installed")
def test_secrets_hydrate_leaves_existing_key_untouched(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _stub(bin_dir, "bw", 'echo \'{"status":"unlocked"}\'')
    key = tmp_path / "home" / ".ssh" / "id_ed25519"
    key.parent.mkdir(parents=True)
    key.write_text("existing")
    result = _run(tmp_path, "secrets_hydrate", env={"BW_SESSION": "token"})
    assert result.returncode == 0
    assert key.read_text() == "existing"


@pytest.mark.skipif(shutil.which("jq") is None, reason="jq not installed")
def test_secrets_hydrate_fails_when_item_has_no_key(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _stub(bin_dir, "bw", 'case "$1" in status) echo \'{"status":"unlocked"}\' ;; get) echo \'{}\' ;; esac')
    result = _run(tmp_path, "secrets_hydrate", env={"BW_SESSION": "token"})
    assert result.returncode == 1
    assert not (tmp_path / "home" / ".ssh" / "id_ed25519").exists()
