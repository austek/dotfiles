import os
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "bin" / "claude-reload"
SHIMS = SCRIPT.with_name("claude-reload-shims")
SESSION = "11111111-2222-3333-4444-555555555555"

pytestmark = pytest.mark.skipif(shutil.which("jq") is None, reason="claude-reload needs jq")


def _executable(path: Path, body: str) -> None:
    path.write_text(body)
    path.chmod(0o755)


class Harness:
    """A fake pane: a process holding the session's tasks directory open, and stub tmux, pgrep, cozempic and terminals."""

    def __init__(self, tmp_path: Path):
        self.tmp = tmp_path
        self.bin = tmp_path / "bin"
        self.bin.mkdir()
        self.work = tmp_path / "work"
        self.work.mkdir()
        self.log = tmp_path / "cozempic.log"
        tasks = tmp_path / "data" / SESSION / "tasks"
        tasks.mkdir(parents=True)
        fd = os.open(tasks, os.O_RDONLY)
        self.claude = subprocess.Popen(["sleep", "30"], pass_fds=(fd,))
        os.close(fd)
        sessions = tmp_path / "home/.claude/sessions"
        sessions.mkdir(parents=True)
        (sessions / f"{self.claude.pid}.json").write_text(f'{{"sessionId": "{SESSION}", "cwd": "{self.work}"}}')
        self.tmux_log = tmp_path / "tmux.log"
        _executable(
            self.bin / "tmux",
            f'#!/bin/sh\nprintf "%s\\n" "$*" >> "{self.tmux_log}"\n[ "$1" = display-message ] && echo 4242\nexit 0\n',
        )
        _executable(self.bin / "pgrep", f"#!/bin/sh\necho {self.claude.pid}\n")
        _executable(
            self.bin / "cozempic",
            f'#!/bin/sh\n{{ echo "$@"; command -v gnome-terminal; command -v xterm; }} > "{self.log}"\nexit "${{COZEMPIC_EXIT:-0}}"\n',
        )
        for terminal in ("gnome-terminal", "xterm"):
            _executable(self.bin / terminal, "#!/bin/sh\nexit 0\n")

    def run(self, *args: str, cozempic_exit: int = 0) -> subprocess.CompletedProcess:
        env = {
            "HOME": str(self.tmp / "home"), "PATH": f"{self.bin}:/usr/bin:/bin", "TMUX_PANE": "%1",
            "COZEMPIC_EXIT": str(cozempic_exit),
        }
        return subprocess.run([str(SCRIPT), *args], env=env, capture_output=True, text=True, check=False)

    def tmux_calls(self) -> list[str]:
        return self.tmux_log.read_text().splitlines()

    def close(self) -> None:
        self.claude.kill()
        self.claude.wait()


@pytest.fixture
def pane(tmp_path):
    harness = Harness(tmp_path)
    yield harness
    harness.close()


def test_the_reload_is_run_with_the_default_prescription_for_the_live_session(pane):
    result = pane.run()
    assert result.returncode == 0, result.stderr
    assert pane.log.read_text().splitlines()[0] == f"reload --session {SESSION} -rx standard"


def test_cozempic_finds_the_no_op_terminals_before_the_real_ones(pane):
    pane.run()
    _, gnome, xterm = pane.log.read_text().splitlines()
    assert gnome == str(SHIMS / "gnome-terminal")
    assert xterm == str(SHIMS / "xterm")


def test_the_resume_line_is_buffered_and_pasted_into_the_pane_once_claude_exits(pane):
    assert pane.run().returncode == 0
    calls = pane.tmux_calls()
    buffered = next(c for c in calls if c.startswith("set-buffer -b claude-reload-"))
    assert buffered.endswith(f"-- cd '{pane.work}' && claude --resume {SESSION}")
    watcher = next(c for c in calls if c.startswith("run-shell -b "))
    assert f"kill -0 {pane.claude.pid}" in watcher
    assert "paste-buffer -d -b claude-reload-" in watcher
    assert "-t %1" in watcher


def test_a_failed_reload_keeps_its_status_and_starts_no_watcher(pane):
    result = pane.run(cozempic_exit=3)
    assert result.returncode == 3
    calls = pane.tmux_calls()
    assert any(c.startswith("delete-buffer -b claude-reload-") for c in calls)
    assert not any(c.startswith("run-shell") for c in calls)


@pytest.mark.parametrize("terminal", ["gnome-terminal", "xterm"])
def test_the_shim_terminals_exit_quietly_with_no_output(terminal):
    argv = [str(SHIMS / terminal), "--", "bash", "-c", "claude --resume x"]
    result = subprocess.run(argv, capture_output=True, text=True, check=False)
    assert (result.returncode, result.stdout, result.stderr) == (0, "", "")


def test_a_missing_shims_directory_stops_the_reload_before_anything_runs(pane):
    lone = pane.tmp / "lone"
    lone.mkdir()
    copy = lone / "claude-reload"
    shutil.copy(SCRIPT, copy)
    env = {"HOME": str(pane.tmp / "home"), "PATH": f"{pane.bin}:/usr/bin:/bin", "TMUX_PANE": "%1"}
    result = subprocess.run([str(copy)], env=env, capture_output=True, text=True, check=False)
    assert result.returncode == 1
    assert "claude-reload-shims" in result.stderr
    assert not pane.log.exists()


def test_a_pane_that_is_not_in_tmux_is_refused(tmp_path):
    env = {"HOME": str(tmp_path), "PATH": "/usr/bin:/bin"}
    result = subprocess.run([str(SCRIPT)], env=env, capture_output=True, text=True, check=False)
    assert result.returncode == 1
    assert "run inside a tmux pane" in result.stderr
