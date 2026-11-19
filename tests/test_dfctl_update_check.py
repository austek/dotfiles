import os
import pty
import re
import select
import shutil
import signal
import subprocess
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
FUNCTIONS = ROOT / "zsh" / ".config" / "zsh" / "functions"
PROMPT = "[y/N]"
HINT = "dfctl apply --upgrade when ready"
AGO = "{days} days since the last dfctl apply or reminder."
ASK_LINE = "[dfctl] It has been " + AGO + " Run dfctl apply --upgrade now? [y/N] "
AUTO_LINE = "[dfctl] running dfctl apply --upgrade ({days} days since the last apply or reminder)"
AGE = 9
GITCONFIG = """[user]
\tname = Update Test
\temail = update@example.com
[commit]
\tgpgsign = false
[init]
\tdefaultBranch = main
[core]
\thooksPath = /dev/null
"""
DFCTL_STUB = (
    '#!/bin/sh\nprintf "dfctl %s head=%s\\n" "$*" "$(git -C "$HOME/.dotfiles" rev-parse HEAD)" >> "$STUB_LOG"\n'
    'exit "${DFCTL_RC:-0}"\n'
)


def today() -> int:
    return int(time.time() // 86400)


class Result:
    def __init__(self, output: str):
        self.output = output.replace("\r\n", "\n")


class Env:
    """A temp HOME with a ~/.dotfiles clone of a bare origin, and a stub dfctl on a private PATH."""

    def __init__(self, tmp: Path, zsh: str):
        self.tmp, self.zsh = tmp, zsh
        self.home = tmp / "home"
        self.state = tmp / "state"
        self.bin = tmp / "bin"
        self.tools = tmp / "tools"
        self.log = tmp / "stub.log"
        self.stamp = self.state / "dotfiles" / "update-check"
        self.lock = self.state / "dotfiles" / "update-check.lock"
        self.dot = self.home / ".dotfiles"
        self.other = tmp / "other"
        self.origin = tmp / "origin.git"
        for path in (self.home, self.bin, self.tools):
            path.mkdir()
        (tmp / "gitconfig").write_text(GITCONFIG)
        for name in ("git", "sh", "mkdir", "rmdir", "stty"):
            (self.tools / name).symlink_to(shutil.which(name))
        self.add_stub("dfctl", DFCTL_STUB)
        self.env = {
            "PATH": f"{self.bin}:{self.tools}", "HOME": str(self.home), "XDG_STATE_HOME": str(self.state),
            "GIT_CONFIG_GLOBAL": str(tmp / "gitconfig"), "GIT_CONFIG_NOSYSTEM": "1", "GIT_TERMINAL_PROMPT": "0",
            "STUB_LOG": str(self.log), "TERM": "dumb",
        }
        self.log.write_text("")
        self.git("init", "-q", "--bare", str(self.origin), cwd=tmp)
        self.git("clone", "-q", str(self.origin), str(self.dot), cwd=tmp)
        self.commit(self.dot, "base")
        self.git("push", "-q", "-u", "origin", "main", cwd=self.dot)
        self.git("clone", "-q", str(self.origin), str(self.other), cwd=tmp)

    def add_stub(self, name: str, body: str) -> None:
        path = self.bin / name
        path.write_text(body)
        path.chmod(0o755)

    def remove_tool(self, name: str) -> None:
        for directory in (self.bin, self.tools):
            (directory / name).unlink(missing_ok=True)

    def git(self, *args: str, cwd: Path) -> str:
        return subprocess.run(
            ["git", *args], cwd=cwd, env=self.env, capture_output=True, text=True, check=True,
        ).stdout.strip()

    def commit(self, repo: Path, name: str) -> None:
        (repo / name).write_text(name)
        self.git("add", name, cwd=repo)
        self.git("commit", "-q", "-m", name, cwd=repo)

    def upstream_commit(self) -> str:
        self.git("pull", "-q", cwd=self.other)
        self.commit(self.other, "upstream")
        self.git("push", "-q", "origin", "main", cwd=self.other)
        self.git("fetch", "-q", "origin", cwd=self.dot)
        return self.git("rev-parse", "origin/main", cwd=self.dot)

    def head(self) -> str:
        return self.git("rev-parse", "HEAD", cwd=self.dot)

    def move_state(self, state: Path) -> None:
        self.state = state
        self.stamp = state / "dotfiles" / "update-check"
        self.lock = state / "dotfiles" / "update-check.lock"
        self.env["XDG_STATE_HOME"] = str(state)

    def set_stamp(self, days: int) -> None:
        self.stamp.parent.mkdir(parents=True, exist_ok=True)
        self.stamp.write_text(f"LAST_EPOCH={days}\n")

    def stamp_days(self) -> int | None:
        if not self.stamp.exists():
            return None
        match = re.fullmatch(r"LAST_EPOCH=(\d+)\n?", self.stamp.read_text())
        assert match, self.stamp.read_text()
        return int(match.group(1))

    def calls(self) -> list[str]:
        return self.log.read_text().splitlines()

    def called(self, prefix: str) -> bool:
        return any(line.startswith(prefix) for line in self.calls())

    def run(
        self, key: bytes | int | None = None, stdin_tty: bool = True, stdout_tty: bool = True, zstyles: str = "",
        typed: bytes | None = None, tail: str = "", functions: Path = FUNCTIONS,
    ) -> Result:
        script = (
            f'fpath=("{functions}" $fpath)\nautoload -Uz $fpath[1]/*(:t)\n{zstyles}\n'
            f'dfctl-update-check\nprint -r -- "rc=$?"\n{tail}\n'
        )
        master, slave = pty.openpty()
        if typed is not None:
            os.write(master, typed)
        proc = subprocess.Popen(
            [self.zsh, "-f", "-c", script], env=self.env, cwd=self.tmp, stderr=subprocess.STDOUT,
            stdin=slave if stdin_tty else subprocess.DEVNULL, stdout=slave if stdout_tty else subprocess.PIPE,
        )
        os.close(slave)
        try:
            if not stdout_tty:
                return Result(proc.communicate(timeout=30)[0].decode())
            return Result(self.drive(proc, master, key if stdin_tty else None))
        finally:
            os.close(master)

    @staticmethod
    def drive(proc: subprocess.Popen, master: int, key: bytes | int | None) -> str:
        out, sent, deadline = b"", False, time.time() + 30
        while time.time() < deadline:
            if select.select([master], [], [], 0.1)[0]:
                try:
                    chunk = os.read(master, 4096)
                except OSError:
                    break
                if not chunk:
                    break
                out += chunk
            elif proc.poll() is not None:
                break
            if key is not None and not sent and PROMPT.encode() in out:
                if isinstance(key, bytes):
                    os.write(master, key)
                else:
                    proc.send_signal(key)
                sent = True
        else:
            proc.kill()
            pytest.fail(f"timed out; output so far: {out!r}")
        proc.wait(timeout=10)
        return out.decode(errors="replace")


@pytest.fixture
def env(tmp_path):
    zsh = shutil.which("zsh")
    if zsh is None:
        pytest.skip("zsh not installed")
    return Env(tmp_path, zsh)


@pytest.fixture
def due(env):
    env.set_stamp(today() - AGE)
    return env


def ask(env: Env, key: bytes = b"\n", **kwargs) -> Result:
    result = env.run(key=key, **kwargs)
    assert PROMPT in result.output, result.output
    return result


def test_ask_prompts_with_the_days_since_the_last_run(due):
    result = ask(due)
    assert ASK_LINE.format(days=AGE) in result.output
    assert not due.called("dfctl")


@pytest.mark.parametrize("mode", ["", "bogus", "ask"])
def test_ask_is_the_default_and_the_fallback_for_an_unknown_mode(due, mode):
    zstyles = f"zstyle ':dfctl:update' mode {mode}" if mode else ""
    assert PROMPT in due.run(key=b"\n", zstyles=zstyles).output


def test_disabled_mode_does_nothing(due):
    result = due.run(zstyles="zstyle ':dfctl:update' mode disabled")
    assert PROMPT not in result.output
    assert "[dfctl]" not in result.output
    assert due.calls() == []
    assert due.stamp_days() == today() - AGE


def test_auto_mode_updates_without_asking(due):
    result = due.run(zstyles="zstyle ':dfctl:update' mode auto")
    assert PROMPT not in result.output
    assert AUTO_LINE.format(days=AGE) in result.output
    assert due.called("dfctl apply --upgrade")
    assert due.stamp_days() == today()


def test_the_first_run_writes_the_stamp_without_prompting(env):
    result = env.run()
    assert PROMPT not in result.output
    assert "[dfctl]" not in result.output
    assert env.stamp_days() == today()
    assert env.calls() == []


def test_a_garbled_stamp_is_treated_as_missing(env):
    env.stamp.parent.mkdir(parents=True)
    env.stamp.write_text("nonsense")
    result = env.run()
    assert PROMPT not in result.output
    assert env.stamp_days() == today()


def test_default_stamp_location_follows_home_when_xdg_state_home_is_unset(env):
    del env.env["XDG_STATE_HOME"]
    env.run()
    stamp = env.home / ".local" / "state" / "dotfiles" / "update-check"
    assert stamp.read_text().strip() == f"LAST_EPOCH={today()}"


@pytest.mark.parametrize(("frequency", "age", "prompts"), [
    ("", 6, False), ("", 7, True), ("1", 0, False), ("1", 1, True), ("3", 2, False), ("3", 3, True),
    ("abc", 6, False), ("abc", 7, True), ("2.5", 6, False), ("2.5", 7, True),
    ("0", 0, True), ("-1", 6, False), ("-1", 7, True),
])
def test_frequency_gates_the_prompt_by_stamp_age(env, frequency, age, prompts):
    env.set_stamp(today() - age)
    zstyles = f"zstyle ':dfctl:update' frequency '{frequency}'" if frequency else ""
    result = env.run(key=b"\n", zstyles=zstyles)
    assert (PROMPT in result.output) is prompts
    assert env.stamp_days() == (today() if prompts else today() - age)


@pytest.mark.parametrize(("stdin_tty", "stdout_tty"), [(False, False), (True, False), (False, True)])
def test_silent_unless_stdin_and_stdout_are_ttys(due, stdin_tty, stdout_tty):
    result = due.run(stdin_tty=stdin_tty, stdout_tty=stdout_tty)
    assert PROMPT not in result.output
    assert "[dfctl]" not in result.output
    assert due.calls() == []
    assert due.stamp_days() == today() - AGE


def test_a_held_lock_makes_the_check_silent_and_stays_held(due):
    due.lock.mkdir(parents=True)
    result = due.run()
    assert PROMPT not in result.output
    assert due.calls() == []
    assert due.lock.is_dir()
    assert due.stamp_days() == today() - AGE


def test_a_stale_lock_is_replaced(due):
    due.lock.mkdir(parents=True)
    old = time.time() - 3 * 86400
    os.utime(due.lock, (old, old))
    assert PROMPT in due.run(key=b"\n").output


@pytest.mark.parametrize("key", [b"\n", b"y"])
def test_the_lock_is_removed_when_the_run_ends(due, key):
    due.run(key=key)
    assert not due.lock.exists()


def test_the_lock_is_removed_after_the_first_run(env):
    env.run()
    assert not env.lock.exists()


def test_y_pulls_then_applies_and_stamps(due):
    behind = due.upstream_commit()
    ask(due, key=b"y")
    assert due.head() == behind
    assert any(line.startswith("dfctl apply --upgrade") and f"head={behind}" in line for line in due.calls())
    assert due.stamp_days() == today()


def test_capital_y_runs_the_update(due):
    ask(due, key=b"Y")
    assert due.called("dfctl apply --upgrade")


@pytest.mark.parametrize("key", [b"\n", b"n", b"x"])
def test_any_other_key_snoozes_with_a_hint(due, key):
    due.upstream_commit()
    before = due.head()
    result = ask(due, key=key)
    assert HINT in result.output
    assert not due.called("dfctl")
    assert due.head() == before
    assert due.stamp_days() == today()


def test_snoozing_silences_the_next_shell(due):
    ask(due)
    assert PROMPT not in due.run().output


def test_a_failed_pull_stops_before_apply_and_still_stamps(due):
    due.upstream_commit()
    due.commit(due.dot, "local_only")
    result = ask(due, key=b"y")
    assert not due.called("dfctl")
    assert re.search(r"git pull --ff-only exited with [1-9]\d*[;.,]", result.output)
    assert "dfctl apply --upgrade" in result.output.split(PROMPT)[1]
    assert due.stamp_days() == today()


def test_a_failed_apply_reports_the_code_and_still_stamps(due):
    due.env["DFCTL_RC"] = "3"
    result = ask(due, key=b"y")
    tail = result.output.split(PROMPT)[1]
    assert "dfctl apply --upgrade exited with 3; run it again to retry" in tail
    assert due.stamp_days() == today()
    assert result.output.rstrip().endswith("rc=0")


def test_auto_mode_reports_a_failed_apply(due):
    due.env["DFCTL_RC"] = "4"
    result = due.run(zstyles="zstyle ':dfctl:update' mode auto")
    assert "dfctl apply --upgrade exited with 4; run it again to retry" in result.output
    assert due.stamp_days() == today()


def test_dfctl_falls_back_to_the_dotfiles_checkout(due):
    due.remove_tool("dfctl")
    (due.dot / "bin").mkdir()
    fallback = due.dot / "bin" / "dfctl"
    fallback.write_text('#!/bin/sh\nprintf "checkout-dfctl %s\\n" "$*" >> "$STUB_LOG"\n')
    fallback.chmod(0o755)
    ask(due, key=b"y")
    assert due.called("checkout-dfctl apply --upgrade")


def test_no_pull_when_the_checkout_is_not_on_main(due):
    due.upstream_commit()
    due.git("switch", "-q", "-c", "topic", cwd=due.dot)
    before = due.head()
    ask(due, key=b"y")
    assert due.head() == before
    assert due.called("dfctl apply --upgrade")


def test_apply_still_runs_without_git_or_a_checkout(due):
    due.remove_tool("git")
    shutil.rmtree(due.dot / ".git")
    ask(due, key=b"y")
    assert due.called("dfctl apply --upgrade")
    assert due.stamp_days() == today()


def test_a_future_stamp_is_rewritten_silently(env):
    env.set_stamp(today() + 3)
    result = env.run()
    assert PROMPT not in result.output
    assert "[dfctl]" not in result.output
    assert env.stamp_days() == today()
    assert env.calls() == []


def test_an_empty_xdg_state_home_falls_back_to_the_home_state_dir(env):
    env.env["XDG_STATE_HOME"] = ""
    env.run()
    stamp = env.home / ".local" / "state" / "dotfiles" / "update-check"
    assert stamp.read_text().strip() == f"LAST_EPOCH={today()}"


def test_a_state_path_with_spaces_works(env, tmp_path):
    env.move_state(tmp_path / "state dir" / "x y")
    env.set_stamp(today() - AGE)
    ask(env, key=b"y")
    assert env.called("dfctl apply --upgrade")
    assert env.stamp_days() == today()
    assert not env.lock.exists()


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores directory permissions")
def test_an_unwritable_state_dir_is_silent_and_does_not_loop(due):
    due.stamp.parent.chmod(0o500)
    try:
        result = due.run()
    finally:
        due.stamp.parent.chmod(0o700)
    assert PROMPT not in result.output
    assert "[dfctl]" not in result.output
    assert result.output.rstrip().endswith("rc=0")
    assert due.calls() == []


def test_a_lock_younger_than_an_hour_is_not_replaced(due):
    due.lock.mkdir(parents=True)
    recent = time.time() - 1800
    os.utime(due.lock, (recent, recent))
    result = due.run()
    assert PROMPT not in result.output
    assert due.calls() == []
    assert due.lock.is_dir()


def test_the_lock_is_removed_after_an_interrupt_at_the_prompt(due):
    result = due.run(key=signal.SIGINT)
    assert PROMPT in result.output
    assert not due.lock.exists()


def test_zshrc_calls_the_check_after_oh_my_zsh_and_the_function_autoload():
    lines = (ROOT / "zsh" / ".zshrc").read_text().splitlines()
    calls = [i for i, line in enumerate(lines) if line.strip() == "dfctl-update-check"]
    autoload = next(i for i, line in enumerate(lines) if line.startswith("autoload -Uz $fpath[1]/"))
    omz = next(i for i, line in enumerate(lines) if line.strip() == "source $ZSH/oh-my-zsh.sh")
    secrets = [i for i, line in enumerate(lines) if "~/.zshrc.secret" in line or "~/.config/dotfiles/secrets.env" in line]
    assert len(calls) == 1
    assert calls[0] > autoload > omz
    assert secrets
    assert calls[0] > max(secrets)


REMINDER_STYLE = "zstyle ':dfctl:update' mode reminder"
REMINDER = "[dfctl] It has been " + AGO + " Run dfctl apply --upgrade when you are ready."
LEFT = "left=q"
READ_BACK = 'read -r -k 1 -t 2 left; print -r -- "left=$left"'


def test_reminder_mode_prints_one_line_and_does_nothing_else(due):
    result = due.run(zstyles=REMINDER_STYLE, typed=b"q", tail=READ_BACK)
    assert REMINDER.format(days=AGE) in result.output
    assert result.output.count("[dfctl]") == 1
    assert PROMPT not in result.output
    assert HINT not in result.output
    assert due.calls() == []
    assert LEFT in result.output


def test_reminder_mode_snoozes_by_writing_the_stamp(due):
    due.run(zstyles=REMINDER_STYLE)
    assert due.stamp_days() == today()
    assert "[dfctl]" not in due.run(zstyles=REMINDER_STYLE).output


@pytest.mark.parametrize(("stamp_age", "reminds"), [(6, False), (7, True), (AGE, True)])
def test_reminder_mode_honours_the_frequency(env, stamp_age, reminds):
    env.set_stamp(today() - stamp_age)
    result = env.run(zstyles=REMINDER_STYLE)
    assert (REMINDER.format(days=stamp_age) in result.output) is reminds
    assert env.stamp_days() == (today() if reminds else today() - stamp_age)


def test_reminder_mode_first_run_and_garbled_stamp_stay_silent(env):
    assert "[dfctl]" not in env.run(zstyles=REMINDER_STYLE).output
    assert env.stamp_days() == today()
    env.stamp.write_text("nonsense")
    assert "[dfctl]" not in env.run(zstyles=REMINDER_STYLE).output
    assert env.stamp_days() == today()


def test_reminder_mode_future_stamp_is_rewritten_silently(env):
    env.set_stamp(today() + 3)
    assert "[dfctl]" not in env.run(zstyles=REMINDER_STYLE).output
    assert env.stamp_days() == today()


@pytest.mark.parametrize(("stdin_tty", "stdout_tty"), [(False, False), (True, False), (False, True)])
def test_reminder_mode_is_silent_without_ttys(due, stdin_tty, stdout_tty):
    result = due.run(zstyles=REMINDER_STYLE, stdin_tty=stdin_tty, stdout_tty=stdout_tty)
    assert "[dfctl]" not in result.output
    assert due.stamp_days() == today() - AGE


def test_reminder_mode_is_silent_when_the_lock_is_held(due):
    due.lock.mkdir(parents=True)
    assert "[dfctl]" not in due.run(zstyles=REMINDER_STYLE).output
    assert due.stamp_days() == today() - AGE


def test_reminder_mode_releases_the_lock(due):
    due.run(zstyles=REMINDER_STYLE)
    assert not due.lock.exists()


def test_ask_mode_reminds_instead_of_prompting_when_input_is_pending(due):
    result = due.run(typed=b"q", tail=READ_BACK)
    assert REMINDER.format(days=AGE) in result.output
    assert PROMPT not in result.output
    assert due.calls() == []
    assert due.stamp_days() == today()
    assert LEFT in result.output


def test_ask_mode_still_prompts_when_nothing_is_typed(due):
    assert PROMPT in due.run(key=b"\n").output


STTY_BEFORE = 'print -r -- "before=$(stty -g)"'
STTY_AFTER = 'print -r -- "after=$(stty -g)"'


def test_the_functions_load_from_a_path_with_a_space(due, tmp_path):
    copy = tmp_path / "dot files" / "functions"
    shutil.copytree(FUNCTIONS, copy)
    result = due.run(key=b"\n", functions=copy)
    assert PROMPT in result.output
    assert "not found" not in result.output


@pytest.mark.parametrize("typed", [b"q", None])
def test_the_terminal_settings_are_restored_after_the_pending_input_check(due, typed):
    result = due.run(key=b"\n", typed=typed, zstyles=STTY_BEFORE, tail=STTY_AFTER)
    before = re.search(r"before=(\S+)", result.output)
    after = re.search(r"after=(\S+)", result.output)
    assert before
    assert after
    assert before.group(1) == after.group(1)


def test_a_missing_zselect_module_falls_back_to_the_prompt_quietly(due):
    stub = 'zmodload() { [[ $1 == zsh/zselect ]] && return 1; builtin zmodload "$@" }'
    result = due.run(key=b"\n", typed=b"q", zstyles=stub)
    assert PROMPT in result.output
    assert "zselect" not in result.output
    assert "zmodload" not in result.output
    assert due.stamp_days() == today()


def test_ask_mode_without_stty_still_prompts(due):
    due.remove_tool("stty")
    assert PROMPT in due.run(key=b"\n").output


def test_a_pending_input_reminder_snoozes_the_next_shell(due):
    assert REMINDER.format(days=AGE) in due.run(typed=b"q").output
    assert "[dfctl]" not in due.run(typed=b"q").output


def test_auto_mode_ignores_pending_input(due):
    result = due.run(zstyles="zstyle ':dfctl:update' mode auto", typed=b"q")
    assert "running dfctl apply --upgrade" in result.output
    assert due.called("dfctl apply --upgrade")
