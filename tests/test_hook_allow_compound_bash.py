"""Tests for claude/.claude/hooks/allow-compound-bash.py."""
import sys

sys.dont_write_bytecode = True  # keep __pycache__ out of the stowed hooks package

import contextlib
import importlib.util
import io
import json
from pathlib import Path

import pytest

HOOK = Path(__file__).resolve().parent.parent / "claude" / ".claude" / "hooks" / "allow-compound-bash.py"
spec = importlib.util.spec_from_file_location("allow_compound_bash", HOOK)
hook = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hook)

RULES = {
    "allow": [hook.to_regex(p) for p in ("git *", "gh *", "./gradlew *test*", "find *", "xargs *")],
    "deny": [hook.to_regex("git push * main*")],
    "ask": [],
}


def allowed(command):
    return hook.analyze(command, RULES)


def test_every_segment_on_the_allowlist_is_allowed():
    assert allowed("git status && gh pr list | head -5")


def test_one_unlisted_segment_defers_to_the_prompt():
    assert not allowed("git status && rm file")


def test_deny_rule_beats_allow_rule():
    assert not allowed("git push origin main")


def test_safe_commands_need_no_rule():
    assert allowed("ls /tmp | wc -l")


@pytest.mark.parametrize("command", [
    "sort -o out.txt in.txt", "sort -oout.txt in.txt", "sort -uo out.txt in.txt",
    "sort --output=out.txt in.txt", "date -s 2020-01-01", "date --set=2020-01-01",
    "sort --compress-program=sh in.txt", "uniq /dev/null out.txt",
])
def test_write_flags_on_safe_commands_are_rejected_in_every_form(command):
    assert not allowed(command)


@pytest.mark.parametrize("command", ["find . -exec rm {} +", "find . -delete", "find . -okdir rm {} ;"])
def test_find_that_executes_or_deletes_is_rejected(command):
    assert not allowed(command)


def test_plain_find_is_allowed():
    assert allowed("find . -name '*.py'")


def test_xargs_inner_command_is_never_auto_allowed():
    assert not allowed("git ls-files | xargs rm")


def _run_hook(monkeypatch, tmp_path, command):
    payload = {"tool_name": "Bash", "tool_input": {"command": command}, "cwd": str(tmp_path)}
    out = io.StringIO()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(hook, "load_rules", lambda cwd: RULES)
    monkeypatch.setattr(hook.sys, "stdin", io.StringIO(json.dumps(payload)))
    with contextlib.redirect_stdout(out):
        rc = hook.main()
    return rc, out.getvalue().strip()


def test_rule042_safe_pipeline_and_chain_emits_allow(monkeypatch, tmp_path):
    rc, out = _run_hook(monkeypatch, tmp_path, "ls | grep foo && echo done")
    assert rc == 0
    assert json.loads(out)["hookSpecificOutput"]["permissionDecision"] == "allow"


def test_rule042_sensitive_path_gets_no_decision(monkeypatch, tmp_path):
    assert _run_hook(monkeypatch, tmp_path, "cat ~/.ssh/id_rsa") == (0, "")


def test_rule042_tmp_sink_allowed_but_home_sink_not():
    assert allowed("echo hi > /tmp/out.txt")
    assert not allowed("echo hi > ~/file")


@pytest.mark.parametrize("command", ["git push origin main", "cat ~/.ssh/id_rsa", "rm -rf /", "git status && rm file"])
def test_rule042_never_emits_a_decision_for_unsafe_commands(monkeypatch, tmp_path, command):
    assert _run_hook(monkeypatch, tmp_path, command) == (0, "")


def test_rule042_unsafe_substitution_blocks_the_allow():
    assert not allowed("echo $(rm file)")


@pytest.mark.parametrize("command", ["echo a\\ #; rm x", "echo \\;#; rm x"])
def test_hash_after_escaped_char_is_not_a_comment(command):
    assert not allowed(command)


@pytest.mark.parametrize("command", ["for HOME in /tmp; do git status; done", "for PATH in /tmp; do git status; done"])
def test_for_loop_over_exported_or_unsafe_variable_is_rejected(command):
    assert not allowed(command)


def test_printf_v_is_rejected():
    assert not allowed("printf -v HOME /tmp; git status")


@pytest.mark.parametrize("command", [
    "sort --out=/tmp/zz in", "A=-o; sort $A /tmp/zz in", "sort $(echo -o) /tmp/zz in",
    "sort $'-o' /tmp/zz in", "date --se=1", "find . $(echo -delete)",
])
def test_hidden_or_abbreviated_flags_are_rejected(command):
    assert not allowed(command)


@pytest.mark.parametrize("command", [
    "cat ~/.s[s]h/i[d]_rsa", "cat ~/.ss?/id_r*", "cat /etc/{shadow,passwd}", "ls src/*.py", "cat .en?", "cat i[d]_rsa",
    "grep foo .en?", "grep -rn foo ./src/*", "egrep foo cred?",
    "jq -R . .en?", "jq -Rr . cred?",
])
def test_globbed_paths_on_safe_commands_are_rejected(command):
    assert not allowed(command)


@pytest.mark.parametrize("command", [
    "jq '.a[0]' f.json", "grep 'a[0-9]*' f.txt", "tr '[:lower:]' '[:upper:]'",
    "grep 'a.*b' file.txt", "grep -rn 'a[0-9]' src",
])
def test_patterns_that_are_not_paths_stay_allowed(command):
    assert allowed(command)


@pytest.mark.parametrize("command", ["find . -fprint /tmp/x", "find . -fprintf /tmp/x %p", "find . -fls /tmp/x"])
def test_find_file_writing_actions_are_rejected(command):
    assert not allowed(command)


@pytest.mark.parametrize("command", ["jq -n env", "jq -n '$ENV'", "jq -n '$ENV.HOME'"])
def test_env_dumps_through_jq_are_rejected(command):
    assert not allowed(command)


def test_unlisted_command_is_never_a_safe_command():
    assert not allowed("uniq /dev/null out.txt")
    assert "uniq" not in hook.SAFE_COMMANDS


@pytest.mark.parametrize("command", [
    "cat ~/.config/dotfiles/secrets.env", "cat ~/.claude/.credentials.json",
    "cat < /dev/tcp/1.2.3.4/80", "X=~/.ssh/id_rsa; cat $X", "echo $ANTHROPIC_API_KEY",
])
def test_secret_sources_are_rejected(command):
    assert not allowed(command)


def test_tmp_and_devnull_sinks_are_allowed():
    assert allowed("git log > /tmp/out.txt 2>/dev/null")


def test_other_write_targets_are_rejected():
    assert not allowed("git log > ~/notes.txt")


def test_path_traversal_out_of_tmp_is_rejected():
    assert not allowed("git log > /tmp/../etc/passwd")


def test_expandable_sink_target_is_rejected():
    assert not allowed("P=../etc/x; echo hi > /tmp/$P")


def test_sensitive_paths_are_rejected():
    assert not allowed("cat ~/.ssh/id_rsa")


def test_substitution_is_checked_recursively():
    assert allowed("echo $(git rev-parse HEAD)")
    assert not allowed("echo $(rm file)")


def test_unsafe_variable_assignment_is_rejected():
    assert not allowed("PATH=/tmp/bin git status")


def test_assignment_to_exported_variable_is_rejected(monkeypatch):
    monkeypatch.setenv("BROWSER", "xdg-open")
    assert not allowed("BROWSER=cmd; gh pr view")


def test_variable_command_word_is_rejected():
    assert not allowed("$CMD status")


def test_for_loop_body_is_checked():
    assert allowed("for f in a b; do git show $f; done")
    assert not allowed("for f in a b; do rm $f; done")
