import contextlib
import os
import pty
import select
import signal
import subprocess
from pathlib import Path

import pytest

LOOP = Path(__file__).parent.parent / "bin" / "claude-pane-loop"


def _fake_claude(tmp_path):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    claude = fake_bin / "claude"
    claude.write_text(f'#!/bin/sh\necho "$@" >> "{tmp_path}/runs"\necho "${{FOO_CFG:-unset}}" >> "{tmp_path}/cfgs"\n')
    claude.chmod(0o755)
    return fake_bin


def _readline(stream, timeout):
    ready, _, _ = select.select([stream], [], [], timeout)
    if not ready:
        raise TimeoutError(f"pane loop printed nothing within {timeout}s")
    return stream.readline()


def _run_on_tty(tmp_path, typed, grace="2", command=("claude", "first"), type_ahead=False, read_timeout=10):
    """Runs the loop on a pty, typing `typed` plus a closing Enter once the wait prompt appears (or at once
    when `type_ahead`) so a resumed claude's own wait ends without the grace period; returns (exit code, runs)."""
    master, slave = pty.openpty()
    env = {"PATH": f"{_fake_claude(tmp_path)}:/usr/bin:/bin", "CLAUDE_TMUX_GRACE": grace}
    proc = subprocess.Popen(
        [str(LOOP), *command], stdin=slave, stdout=subprocess.PIPE, env=env, text=True, cwd=tmp_path,
        start_new_session=True,
    )
    os.close(slave)
    try:
        keys = None if typed is None else f"{typed}\n".encode()
        if type_ahead:
            os.write(master, keys)
        _readline(proc.stdout, read_timeout)
        if keys is not None and not type_ahead:
            os.write(master, keys)
        code = proc.wait(timeout=15)
    finally:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(proc.pid, signal.SIGKILL)
        proc.stdout.close()
        os.close(master)
    runs = tmp_path / "runs"
    return code, runs.read_text().split("\n")[:-1] if runs.exists() else []


def test_without_a_tty_it_returns_the_commands_status_at_once(tmp_path):
    result = subprocess.run(
        [str(LOOP), "sh", "-c", "exit 7"], check=False, stdin=subprocess.DEVNULL, capture_output=True, text=True,
    )
    assert result.returncode == 7
    assert result.stdout == ""


def test_a_typed_resume_line_restarts_claude_in_place(tmp_path):
    code, runs = _run_on_tty(tmp_path, f"cd '{tmp_path}' && claude --resume abc\n")
    assert runs == ["first", "--resume abc"]
    assert code == 0


def test_env_assignments_before_claude_carry_over_to_the_resumed_claude(tmp_path):
    _run_on_tty(tmp_path, f"cd '{tmp_path}' && claude --resume abc\n", command=("env", "FOO_CFG=burst", "claude", "first"))
    assert (tmp_path / "cfgs").read_text().split() == ["burst", "burst"]


def test_other_typed_input_ends_the_pane_without_running_it(tmp_path):
    _, runs = _run_on_tty(tmp_path, f"cd '{tmp_path}'; touch pwned && claude\n")
    assert runs == ["first"]
    assert not (tmp_path / "pwned").exists()


def test_enter_alone_ends_the_pane(tmp_path):
    _, runs = _run_on_tty(tmp_path, "\n")
    assert runs == ["first"]


def test_the_pane_ends_when_no_resume_arrives_within_the_grace_period(tmp_path):
    _, runs = _run_on_tty(tmp_path, None, grace="0")
    assert runs == ["first"]


def test_a_resume_line_typed_while_claude_runs_still_restarts_it(tmp_path):
    code, runs = _run_on_tty(tmp_path, f"cd '{tmp_path}' && claude --resume abc\n", type_ahead=True)
    assert runs == ["first", "--resume abc"]
    assert code == 0


def test_a_hung_command_times_out_instead_of_blocking_the_reader(tmp_path):
    with pytest.raises(TimeoutError):
        _run_on_tty(tmp_path, None, command=("sh", "-c", "exec sleep 30"), read_timeout=0.2)
