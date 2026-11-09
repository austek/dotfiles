import os
import pty
import shutil
import subprocess
from pathlib import Path

import pytest

FUNCTIONS = (
    Path(__file__).resolve().parent.parent / "zsh" / ".config" / "zsh" / "functions"
)

pytestmark = pytest.mark.skipif(shutil.which("zsh") is None, reason="zsh not installed")

RECORDER = '#!/bin/sh\nprintf claude >> "$LOG"\nfor a in "$@"; do printf "\\037%s" "$a" >> "$LOG"; done\nprintf "\\n" >> "$LOG"\n'

EXTENSION = (
    "restore_argv_tricky=(claude mcp add tricky -H 'X-Note: a b; touch PWNED' -e 'TOKEN=${TRICKY_TOKEN}' -s local)\n"
    "revert_argv_tricky=(claude mcp remove tricky -s local)\n"
    "claude_with_secrets_tricky=(TRICKY_TOKEN)\n"
    "restore_argv_dash_name=(claude mcp add dash)\n"
    "revert_argv_dash_name=(claude mcp remove dash)\n"
)


def _setup(tmp_path: Path, extension: str = "") -> dict[str, str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name in ("claude", "tmux"):
        stub = bin_dir / name
        stub.write_text(RECORDER.replace("claude", name, 1))
        stub.chmod(0o755)
    home = tmp_path / "home"
    (home / ".config" / "zsh" / "claude-with.d").mkdir(parents=True)
    (home / ".config" / "zsh" / "claude-with.d" / "ext.zsh").write_text(extension)
    return {
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "HOME": str(home),
        "LOG": str(tmp_path / "log"),
    }


def _run(
    tmp_path: Path, script: str, env: dict[str, str]
) -> subprocess.CompletedProcess:
    setup = f"fpath=({FUNCTIONS} $fpath); autoload -Uz claude-with claude-tmux\n"
    return subprocess.run(
        ["zsh", "-f", "-c", setup + script],
        capture_output=True,
        text=True,
        env=env,
        cwd=tmp_path,
        timeout=30,
        check=False,
    )


def _calls(tmp_path: Path) -> list[list[str]]:
    log = tmp_path / "log"
    return (
        [line.split("\x1f") for line in log.read_text().splitlines()]
        if log.exists()
        else []
    )


def test_argv_boundaries_are_exact_and_placeholders_stay_literal(tmp_path):
    env = _setup(tmp_path, EXTENSION) | {"TRICKY_TOKEN": "s3cret"}
    result = _run(tmp_path, "claude-with tricky -- --resume 'a b'", env)
    assert result.returncode == 0, result.stderr
    calls = _calls(tmp_path)
    assert calls[0] == [
        "claude",
        "mcp",
        "add",
        "tricky",
        "-H",
        "X-Note: a b; touch PWNED",
        "-e",
        "TOKEN=${TRICKY_TOKEN}",
        "-s",
        "local",
    ]
    assert calls[1] == ["claude", "--resume", "a b"]
    assert calls[2] == ["claude", "mcp", "remove", "tricky", "-s", "local"]
    assert not (tmp_path / "PWNED").exists()


def test_builtin_grafana_placeholder_is_passed_unexpanded(tmp_path):
    env = _setup(tmp_path) | {"GRAFANA_SERVICE_ACCOUNT_TOKEN": "s3cret"}
    result = _run(tmp_path, "claude-with grafana", env)
    assert result.returncode == 0, result.stderr
    assert (
        "GRAFANA_SERVICE_ACCOUNT_TOKEN=${GRAFANA_SERVICE_ACCOUNT_TOKEN}"
        in _calls(tmp_path)[0]
    )


def test_missing_placeholder_secret_skips_the_entry(tmp_path):
    env = _setup(tmp_path, EXTENSION)
    result = _run(tmp_path, "claude-with tricky", env)
    assert result.returncode == 1
    assert "$TRICKY_TOKEN is not set" in result.stderr
    assert _calls(tmp_path) == []


def test_hyphenated_name_maps_to_underscored_array(tmp_path):
    env = _setup(tmp_path, EXTENSION)
    result = _run(tmp_path, "claude-with dash-name", env)
    assert result.returncode == 0, result.stderr
    assert _calls(tmp_path)[0] == ["claude", "mcp", "add", "dash"]


@pytest.mark.parametrize(
    "name", ["idea[$(touch PWNED)]", "tricky[@]", "idea[1]", "a b", "x;y"]
)
def test_names_outside_the_safe_set_are_rejected_without_evaluation(tmp_path, name):
    env = _setup(tmp_path, EXTENSION)
    result = _run(tmp_path, f"claude-with {_zsh_quote(name)}", env)
    assert f"invalid name '{name}' (allowed: letters, digits, _ and -)" in result.stderr
    assert not (tmp_path / "PWNED").exists()
    assert _calls(tmp_path) == []


def _zsh_quote(text: str) -> str:
    return "'" + text.replace("'", "'\\''") + "'"


def test_revert_runs_on_sigterm_and_exit_status_is_143(tmp_path):
    env = _setup(tmp_path)
    (tmp_path / "bin" / "claude").write_text(
        RECORDER + 'case "$1" in mcp) ;; *) kill -TERM $PPID; sleep 0.3 ;; esac\n'
    )
    result = _run(tmp_path, "claude-with idea", env)
    assert result.returncode == 143
    assert ["claude", "mcp", "remove", "idea", "-s", "local"] in _calls(tmp_path)


def test_claude_exit_status_is_propagated_after_revert(tmp_path):
    env = _setup(tmp_path)
    (tmp_path / "bin" / "claude").write_text(
        RECORDER + 'case "$1" in mcp) ;; *) exit 7 ;; esac\n'
    )
    result = _run(tmp_path, "claude-with idea", env)
    assert result.returncode == 7
    assert _calls(tmp_path)[-1] == ["claude", "mcp", "remove", "idea", "-s", "local"]


def test_already_enabled_is_left_alone_and_not_reverted(tmp_path):
    env = _setup(tmp_path)
    (tmp_path / "bin" / "claude").write_text(
        RECORDER + 'case "$1" in mcp) echo "already exists" >&2; exit 1 ;; esac\n'
    )
    result = _run(tmp_path, "claude-with idea", env)
    assert "idea already enabled" in result.stdout
    assert not any(call[1:3] == ["mcp", "remove"] for call in _calls(tmp_path))


def test_unknown_valid_name_keeps_the_no_restore_entry_message(tmp_path):
    result = _run(tmp_path, "claude-with nope", _setup(tmp_path))
    assert "no restore entry for 'nope'" in result.stderr
    assert result.returncode == 1


def test_entry_without_revert_is_skipped_and_reported(tmp_path):
    ext = "restore_argv_norev=(claude mcp add norev)\n"
    result = _run(tmp_path, "claude-with norev idea", _setup(tmp_path, ext))
    assert "no revert entry for 'norev'" in result.stderr
    assert "claude-with: running WITHOUT: norev" in result.stderr
    assert not any(call[1:4] == ["mcp", "add", "norev"] for call in _calls(tmp_path))
    assert any(call[1:4] == ["mcp", "add", "--transport"] for call in _calls(tmp_path))


def test_partial_skip_warns_before_launching_claude(tmp_path):
    env = _setup(tmp_path, EXTENSION)
    result = _run(tmp_path, "claude-with idea tricky nope -- go", env)
    assert result.returncode == 0
    assert "claude-with: running WITHOUT: tricky nope" in result.stderr
    assert _calls(tmp_path)[1] == ["claude", "go"]


def test_failed_add_counts_as_skipped(tmp_path):
    env = _setup(tmp_path)
    (tmp_path / "bin" / "claude").write_text(
        RECORDER + 'case "$1" in mcp) echo boom >&2; exit 1 ;; esac\n'
    )
    result = _run(tmp_path, "claude-with idea", env)
    assert "failed to add idea" in result.stderr
    assert "nothing enabled, aborting" in result.stderr
    assert result.returncode == 1


def test_all_skipped_does_not_print_running_without(tmp_path):
    result = _run(tmp_path, "claude-with nope", _setup(tmp_path))
    assert "running WITHOUT" not in result.stderr


def test_failed_revert_tells_the_user_how_to_clean_up(tmp_path):
    env = _setup(tmp_path)
    (tmp_path / "bin" / "claude").write_text(
        RECORDER + 'case "$2" in remove) exit 1 ;; esac\n'
    )
    result = _run(tmp_path, "claude-with idea", env)
    assert (
        "claude-with: failed to revert idea; run: claude mcp remove idea -s local"
        in result.stderr
    )


def test_failed_revert_hint_shows_the_entrys_own_revert_command(tmp_path):
    extension = (
        "restore_argv_plug=(claude mcp add plug)\n"
        "revert_argv_plug=(claude plugin disable 'my plug')\n"
    )
    env = _setup(tmp_path, extension)
    (tmp_path / "bin" / "claude").write_text(
        RECORDER + 'case "$2" in disable) exit 1 ;; esac\n'
    )
    result = _run(tmp_path, "claude-with plug", env)
    assert (
        "failed to revert plug; run: claude plugin disable my\\ plug" in result.stderr
    )


def test_old_restore_commands_format_is_flagged(tmp_path):
    ext = 'restore_commands[old]="claude mcp add old"\nrevert_commands[old]="claude mcp remove old"\n'
    result = _run(tmp_path, "claude-with idea", _setup(tmp_path, ext))
    assert "uses the removed restore_commands format" in result.stderr
    assert (
        "restore_argv_<id>/revert_argv_<id>/claude_with_secrets_<id>" in result.stderr
    )


def test_invalid_declared_secret_name_skips_the_entry(tmp_path):
    ext = "restore_argv_bad=(claude mcp add bad)\nrevert_argv_bad=(claude mcp remove bad)\nclaude_with_secrets_bad=('X;y')\n"
    result = _run(tmp_path, "claude-with bad idea", _setup(tmp_path, ext))
    assert "invalid secret name 'X;y'" in result.stderr
    assert "running WITHOUT: bad" in result.stderr
    assert not any(call[1:4] == ["mcp", "add", "bad"] for call in _calls(tmp_path))


def _pty_run(tmp_path: Path, script: str, env: dict[str, str]) -> None:
    master, slave = pty.openpty()
    setup = f"fpath=({FUNCTIONS} $fpath); autoload -Uz claude-with\n"
    try:
        subprocess.run(
            ["zsh", "-f", "-c", setup + script],
            stdin=slave,
            stdout=slave,
            stderr=slave,
            env=env,
            cwd=tmp_path,
            timeout=30,
            check=False,
        )
    finally:
        os.close(master)
        os.close(slave)


def _tmux_stub(tmp_path: Path) -> dict[str, str]:
    env = _setup(tmp_path)
    stub = tmp_path / "bin" / "claude-tmux"
    stub.write_text(RECORDER.replace("claude", "claude-tmux", 1))
    stub.chmod(0o755)
    return env


def _cksum(text: str) -> str:
    return (
        subprocess.run(["cksum"], input=text.encode(), capture_output=True, check=True)
        .stdout.split()[0]
        .decode()
    )


def test_tmux_reexec_forwards_session_name_and_arguments_intact(tmp_path):
    env = _tmux_stub(tmp_path)
    _pty_run(tmp_path, "claude-with sonarqube idea -- --resume 'a b'", env)
    call = _calls(tmp_path)[0]
    session = f"with-idea-sonarqube-{_cksum('sonarqube idea -- --resume a b')}"
    assert call == [
        "claude-tmux",
        session,
        "zsh",
        "-ic",
        'claude-with "$@"',
        "claude-with",
        "sonarqube",
        "idea",
        "--",
        "--resume",
        "a b",
    ]


def test_tmux_session_name_is_stable_across_runs(tmp_path):
    env = _tmux_stub(tmp_path)
    _pty_run(tmp_path, "claude-with idea; claude-with idea", env)
    calls = _calls(tmp_path)
    assert len(calls) == 2
    assert calls[0][1] == calls[1][1]


def test_tmux_session_selection_stops_at_double_dash(tmp_path):
    env = _tmux_stub(tmp_path)
    _pty_run(tmp_path, "claude-with idea -- zzz aaa", env)
    assert _calls(tmp_path)[0][1].startswith("with-idea-")


@pytest.mark.parametrize("flag", ["--print", "-p"])
def test_print_flag_bypasses_the_tmux_reexec(tmp_path, flag):
    env = _tmux_stub(tmp_path)
    _pty_run(tmp_path, f"claude-with idea -- {flag} hi", env)
    calls = _calls(tmp_path)
    assert all(call[0] != "claude-tmux" for call in calls)
    assert ["claude", flag, "hi"] in calls


def test_tmux_env_bypasses_the_reexec(tmp_path):
    env = _tmux_stub(tmp_path) | {"TMUX": "/tmp/x,1,0"}
    _pty_run(tmp_path, "claude-with idea", env)
    calls = _calls(tmp_path)
    assert all(call[0] != "claude-tmux" for call in calls)
    assert ["claude"] in calls
