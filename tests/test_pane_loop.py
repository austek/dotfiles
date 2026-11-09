import contextlib
import json
import os
import pty
import select
import shutil
import signal
import subprocess
from pathlib import Path

import pytest

LOOP = Path(__file__).parent.parent / "bin" / "claude-pane-loop"
GRACE = "5"


def _fake_claude(tmp_path):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    claude = fake_bin / "claude"
    claude.write_text(
        f'#!/bin/sh\necho "$@" >> "{tmp_path}/runs"\necho "${{FOO_CFG:-unset}}" >> "{tmp_path}/cfgs"\n'
        f'pwd >> "{tmp_path}/pwds"\n'
        f"printf '%s\\0' \"$@\" > \"{tmp_path}/argv0\"\n"
    )
    claude.chmod(0o755)
    return fake_bin


def _readline(stream, timeout):
    ready, _, _ = select.select([stream], [], [], timeout)
    if not ready:
        raise TimeoutError(f"pane loop printed nothing within {timeout}s")
    return stream.readline()


def _run_on_tty(tmp_path, typed, grace=GRACE, command=("claude", "first"), type_ahead=False, read_timeout=10):
    """Runs the loop on a pty, typing the line(s) plus a closing Enter; returns (exit code, runs).

    Stderr lands in tmp_path/stderr. `typed` is a line, a list of lines, or None to type nothing.
    """
    master, slave = pty.openpty()
    env = {
        "PATH": f"{_fake_claude(tmp_path)}:/usr/bin:/bin", "CLAUDE_TMUX_GRACE": grace, "CLAUDE_TMUX_REJECT_PAUSE": "0",
    }
    lines = typed if isinstance(typed, list) else [typed]
    keys = None if typed is None else ("\n".join(lines) + "\n\n").encode()
    with (tmp_path / "stderr").open("w") as err:
        proc = subprocess.Popen(
            [str(LOOP), *command], stdin=slave, stdout=subprocess.PIPE, stderr=err, env=env, text=True,
            cwd=tmp_path, start_new_session=True,
        )
    os.close(slave)
    try:
        if type_ahead and keys is not None:
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


def _quoted(path):
    return "'" + str(path).replace("'", "'\\''") + "'"


def _received(tmp_path):
    return (tmp_path / "argv0").read_bytes().split(b"\0")[:-1]


def _stderr(tmp_path):
    return (tmp_path / "stderr").read_text()


def test_without_a_tty_it_returns_the_commands_status_at_once(tmp_path):
    result = subprocess.run(
        [str(LOOP), "sh", "-c", "exit 7"], check=False, stdin=subprocess.DEVNULL, capture_output=True, text=True,
    )
    assert result.returncode == 7
    assert result.stdout == ""


def test_a_typed_resume_line_restarts_claude_in_place(tmp_path):
    code, runs = _run_on_tty(tmp_path, f"cd '{tmp_path}' && claude --resume abc")
    assert runs == ["first", "--resume abc"]
    assert code == 0


def test_env_assignments_before_claude_carry_over_to_the_resumed_claude(tmp_path):
    _run_on_tty(tmp_path, f"cd '{tmp_path}' && claude --resume abc", command=("env", "FOO_CFG=burst", "claude", "first"))
    assert (tmp_path / "cfgs").read_text().split() == ["burst", "burst"]


def test_env_assignments_stop_at_the_first_non_assignment(tmp_path):
    _run_on_tty(tmp_path, f"cd '{tmp_path}' && claude --resume abc", command=("env", "A=1", "claude", "FOO_CFG=late"))
    assert (tmp_path / "cfgs").read_text().split() == ["unset", "unset"]


def test_two_consecutive_resumes_in_one_session_both_run(tmp_path):
    line = f"cd '{tmp_path}' && claude --resume abc"
    code, runs = _run_on_tty(tmp_path, [line, line.replace("abc", "def")])
    assert runs == ["first", "--resume abc", "--resume def"]
    assert code == 0


def test_enter_alone_ends_the_pane_silently_with_the_previous_status(tmp_path):
    code, runs = _run_on_tty(tmp_path, "", command=("sh", "-c", "exit 7"))
    assert (code, runs, _stderr(tmp_path)) == (7, [], "")


def test_enter_alone_after_claude_ends_the_pane(tmp_path):
    code, runs = _run_on_tty(tmp_path, "")
    assert (code, runs, _stderr(tmp_path)) == (0, ["first"], "")


def test_the_pane_ends_when_no_resume_arrives_within_the_grace_period(tmp_path):
    code, runs = _run_on_tty(tmp_path, None, grace="0")
    assert (code, runs) == (0, ["first"])


def test_a_resume_line_typed_while_claude_runs_still_restarts_it(tmp_path):
    code, runs = _run_on_tty(tmp_path, f"cd '{tmp_path}' && claude --resume abc", type_ahead=True)
    assert runs == ["first", "--resume abc"]
    assert code == 0


def test_a_rejected_line_exits_64_and_reports_the_reason_and_the_line(tmp_path):
    code, runs = _run_on_tty(tmp_path, f"cd '{tmp_path}'; touch pwned && claude")
    err = _stderr(tmp_path)
    assert (code, runs) == (64, ["first"])
    assert err.startswith("claude-pane-loop: resume line rejected (")
    assert "touch" in err
    assert not (tmp_path / "pwned").exists()


def test_flags_before_resume_reach_the_resumed_claude(tmp_path):
    line = f"cd {_quoted(tmp_path)} && claude --remote-control myhost --model opus --dangerously-skip-permissions --resume abc-123"
    _, runs = _run_on_tty(tmp_path, line)
    assert runs == ["first", "--remote-control myhost --model opus --dangerously-skip-permissions --resume abc-123"]


def test_a_bare_resume_without_an_id_is_accepted(tmp_path):
    _, runs = _run_on_tty(tmp_path, f"cd {_quoted(tmp_path)} && claude --resume")
    assert runs == ["first", "--resume"]


def test_a_directory_containing_a_space_is_one_token(tmp_path):
    spaced = tmp_path / "my dir"
    spaced.mkdir()
    _, runs = _run_on_tty(tmp_path, f"cd {_quoted(spaced)} && claude --resume abc")
    assert runs == ["first", "--resume abc"]


def test_a_directory_containing_a_quote_is_decoded(tmp_path):
    quoted = tmp_path / "it's"
    quoted.mkdir()
    _, runs = _run_on_tty(tmp_path, f"cd {_quoted(quoted)} && claude --resume abc")
    assert runs == ["first", "--resume abc"]


def test_the_resumed_claude_runs_inside_the_typed_directory(tmp_path):
    target = tmp_path / "proj"
    target.mkdir()
    _run_on_tty(tmp_path, f"cd {_quoted(target)} && claude --resume abc")
    assert (tmp_path / "pwds").read_text().split() == [str(tmp_path), str(target)]


@pytest.mark.parametrize(
    "suffix",
    [
        "--resume abc; touch pwned",
        "--resume abc | touch pwned",
        "--resume abc && touch pwned",
        "--resume $(touch pwned)",
        "--resume `touch pwned`",
        "--resume $HOME",
        "--resume ~",
        "--resume *",
        "--resume a?c",
        "--resume [a]",
        "--resume abc > pwned",
        "--resume 'a b'",
        "--resume ABC",
        "--resume xyz",
        "--resume abc ",
        "--resume abc\r",
        "--resume abc --model opus",
        "--model $(touch pwned) --resume abc",
        "--model \"opus\" --resume abc",
        "--model 'a'b --resume abc",
        "--model 'unterminated --resume abc",
        "--model 'a';touch pwned --resume abc",
        "--Model opus --resume abc",
        "--bogus-flag abc",
        "--continue",
        "--model",
        "abc",
        "--resume abc --resume",
        "--dangerously-skip-permissions=$(touch pwned)",
    ],
)
def test_unsafe_or_malformed_arguments_end_the_pane_without_running(tmp_path, suffix):
    code, runs = _run_on_tty(tmp_path, f"cd {_quoted(tmp_path)} && claude {suffix}".replace("\r", "\x16\r"))
    assert (code, runs) == (64, ["first"])
    assert not (tmp_path / "pwned").exists()


@pytest.mark.parametrize(
    "line",
    [
        "cd {d} && claude --resume abc",
        "cd ~ && claude --resume abc",
        "cd '' && claude --resume abc",
        "cd relative && claude --resume abc",
        "cd '{d}/missing' && claude --resume abc",
        "cd '{d}'; touch pwned; claude --resume abc",
        "cd '{d}' && claude --resume abc && touch pwned",
        "cd \"{d}\" && claude --resume abc",
        "cd '{d}' && touch pwned",
        "cd '{d}' && claude; touch pwned",
        "cd 'proj' && claude --resume abc",
        "cd '{d}'$(touch pwned) && claude --resume abc",
        "cd '{d}/*' && claude --resume abc",
        "cd '{d}' && claude --resume abc ",
        "cd '{d}' && claude --resume abc\x16\r",
    ],
)
def test_malformed_directories_and_commands_end_the_pane(tmp_path, line):
    code, runs = _run_on_tty(tmp_path, line.format(d=tmp_path))
    assert (code, runs) == (64, ["first"])
    assert not (tmp_path / "pwned").exists()


def test_an_embedded_quote_cannot_break_out_of_the_directory(tmp_path):
    line = f"cd '{tmp_path}/x'\\''; touch {tmp_path}/pwned; '\\'' && claude --resume abc"
    code, runs = _run_on_tty(tmp_path, line)
    assert (code, runs) == (64, ["first"])
    assert not (tmp_path / "pwned").exists()


# Lines generated once by Cozempic's helpers.shell_quote and guard._detect_claude_flags.
GOLDEN = [
    (r"""cd '@ROOT@/it'\''s a dir' && claude --chrome --resume abc""", ["--chrome", "--resume", "abc"]),
    (
        r"""cd '@ROOT@/it'\''s a dir' && claude --model 'opus[1m]' --resume abc""",
        ["--model", "opus[1m]", "--resume", "abc"],
    ),
    (
        r"""cd '@ROOT@/it'\''s a dir' && claude --remote-control 'my host' --resume abc""",
        ["--remote-control", "my host", "--resume", "abc"],
    ),
    (
        r"""cd '@ROOT@/it'\''s a dir' && claude 'fix it' --verbose --resume abc""",
        ["fix it", "--verbose", "--resume", "abc"],
    ),
    (
        r"""cd '@ROOT@/it'\''s a dir' && claude 'don'"'"'t stop' --add-dir '/tmp/x y' --resume abc""",
        ["don't stop", "--add-dir", "/tmp/x y", "--resume", "abc"],
    ),
    (
        r"""cd '@ROOT@/it'\''s a dir' && claude --model=opus -v --resume abc""",
        ["--model=opus", "-v", "--resume", "abc"],
    ),
    (
        r"""cd '@ROOT@/it'\''s a dir' && claude --model sonnet --chrome --resume abc""",
        ["--model", "sonnet", "--chrome", "--resume", "abc"],
    ),
]


@pytest.mark.parametrize(("template", "expected"), GOLDEN)
def test_golden_cozempic_lines_run_with_the_exact_argv(tmp_path, template, expected):
    (tmp_path / "it's a dir").mkdir()
    _run_on_tty(tmp_path, template.replace("@ROOT@", str(tmp_path)))
    assert _received(tmp_path) == [a.encode() for a in expected]


def _cozempic_python():
    exe = shutil.which("cozempic")
    if exe is None:
        return None
    interpreter = Path(exe).resolve().parent / "python"
    return interpreter if interpreter.exists() else None


COZEMPIC_PY = _cozempic_python()
BUILD_LINE = """
import json, sys, types
import cozempic.guard as guard
from cozempic.helpers import shell_quote
spec = json.load(sys.stdin)
sys.modules["psutil"] = types.SimpleNamespace(
    Process=lambda pid: types.SimpleNamespace(cmdline=lambda: spec["argv"]))
flags = guard._detect_claude_flags(1)
print(f"cd {shell_quote(spec['dir'])} && claude {flags} --resume abc".replace("  ", " "))
"""


def _cozempic_line(directory, argv):
    out = subprocess.run(
        [str(COZEMPIC_PY), "-c", BUILD_LINE], input=json.dumps({"dir": str(directory), "argv": argv}),
        capture_output=True, text=True, check=True,
    )
    return out.stdout.rstrip("\n")


@pytest.mark.skipif(COZEMPIC_PY is None, reason="cozempic is not installed")
@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        (["claude", "--chrome"], ["--chrome", "--resume", "abc"]),
        (["claude", "--model", "opus[1m]"], ["--model", "opus[1m]", "--resume", "abc"]),
        (["claude", "--remote-control", "my host"], ["--remote-control", "my host", "--resume", "abc"]),
        (["claude", "fix it", "--verbose"], ["fix it", "--verbose", "--resume", "abc"]),
        (["claude", "don't stop", "--add-dir", "/tmp/x y"], ["don't stop", "--add-dir", "/tmp/x y", "--resume", "abc"]),
        (["claude", "--model=opus", "-v"], ["--model=opus", "-v", "--resume", "abc"]),
        (["claude", "--model", "sonnet", "--resume", "old-id", "--chrome"], ["--model", "sonnet", "--chrome", "--resume", "abc"]),
    ],
)
def test_lines_built_by_the_installed_cozempic_round_trip_to_the_exact_argv(tmp_path, argv, expected):
    directory = tmp_path / "it's a dir"
    directory.mkdir()
    _run_on_tty(tmp_path, _cozempic_line(directory, argv))
    assert _received(tmp_path) == [a.encode() for a in expected]


def test_dollar_expressions_inside_single_quotes_stay_literal_data(tmp_path):
    _run_on_tty(tmp_path, f"cd {_quoted(tmp_path)} && claude 'fix $(touch pwned) `id`' --resume abc")
    assert _received(tmp_path) == [b"fix $(touch pwned) `id`", b"--resume", b"abc"]
    assert not (tmp_path / "pwned").exists()


def test_glob_characters_inside_single_quotes_are_not_expanded(tmp_path):
    (tmp_path / "file1").write_text("")
    _run_on_tty(tmp_path, f"cd {_quoted(tmp_path)} && claude --model '*' --resume abc")
    assert _received(tmp_path) == [b"--model", b"*", b"--resume", b"abc"]


def test_a_hung_command_times_out_instead_of_blocking_the_reader(tmp_path):
    with pytest.raises(TimeoutError):
        _run_on_tty(tmp_path, None, command=("sh", "-c", "exec sleep 30"), read_timeout=0.2)
