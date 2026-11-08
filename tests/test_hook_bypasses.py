"""Regression tests for bypasses found while reviewing the hook hardening."""
import pytest
from hook_support import HOOKS, RULES, hook, run_hook


@pytest.mark.parametrize("command", [
    "git log \"$(git log -1 $'--output=x')\"",
    'git log "$(git log -1 {--output=x,-n1})"',
    "x='$(touch P)'\n# it's fine\ngit log ${x@P}",
    "git log \"${(e)x}\"",
    "git log $[x]",
    "git log ${a[x]}",
])
def test_expansions_hidden_by_quotes_comments_or_zsh_are_refused(command):
    assert not hook.should_allow(command, RULES)


@pytest.mark.parametrize("command", ["# Claude's check\ngrep -E 'a{1,2}' f.txt", "git log --format='%h %s'"])
def test_a_quote_in_a_comment_no_longer_hides_or_adds_prompts(command):
    assert hook.should_allow(command, RULES)


@pytest.mark.parametrize("command", [
    "cat link/key", "cat ./keyl", "cat keyl", "grep x keyl", "jq . keyl", "ls link",
    "cat < keyl", "cat <link/key", "head -n1 link/key",
])
def test_symlinks_into_secrets_are_refused_for_every_argument_shape(tmp_path, monkeypatch, command):
    (tmp_path / ".ssh").mkdir()
    (tmp_path / ".ssh" / "key").write_text("x")
    (tmp_path / "link").symlink_to(tmp_path / ".ssh")
    (tmp_path / "keyl").symlink_to(tmp_path / ".ssh" / "key")
    monkeypatch.chdir(tmp_path)
    assert not hook.should_allow(command, RULES)


@pytest.mark.parametrize("settings", ["{not json", '{"permissions": []}', '{"permissions": {"deny": "x"}}'])
def test_a_broken_settings_file_means_no_decision(tmp_path, settings):
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "settings.json").write_text(settings)
    payload = {"tool_name": "Bash", "tool_input": {"command": "git status"}, "cwd": str(tmp_path)}
    assert run_hook("allow-compound-bash.py", payload, tmp_path) == ""


def test_a_missing_settings_file_is_not_an_error(tmp_path):
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "settings.json").write_text('{"permissions": {"allow": ["Bash(git *)"]}}')
    payload = {"tool_name": "Bash", "tool_input": {"command": "git status"}, "cwd": str(tmp_path)}
    assert '"allow"' in run_hook("allow-compound-bash.py", payload, tmp_path)


@pytest.mark.parametrize("command", ["grep -fkeyl in.txt", "grep --file=keyl in.txt", "grep -rnfkeyl .", "cat -- -key"])
def test_secret_file_operands_attached_to_flags_or_after_double_dash_are_refused(tmp_path, monkeypatch, command):
    (tmp_path / ".ssh").mkdir()
    (tmp_path / ".ssh" / "key").write_text("x")
    (tmp_path / "keyl").symlink_to(tmp_path / ".ssh" / "key")
    (tmp_path / "-key").symlink_to(tmp_path / ".ssh" / "key")
    monkeypatch.chdir(tmp_path)
    assert not hook.should_allow(command, RULES)


def test_the_rm_hook_denies_a_protected_child_of_a_home_outside_home_and_root(tmp_path):
    home = tmp_path / "srv" / "alice"
    home.mkdir(parents=True)
    protected = {"tool_name": "Bash", "tool_input": {"command": f"rm -rf {home}/Documents"}}
    scratch = {"tool_name": "Bash", "tool_input": {"command": f"rm -rf {home}/scratch"}}
    assert '"deny"' in run_hook("block-dangerous-rm.py", protected, home)
    assert run_hook("block-dangerous-rm.py", scratch, home) == ""


@pytest.mark.parametrize("command", ["git clean -fdx", "find / -delete", "find ~ -delete"])
def test_the_rm_hook_still_denies_these_when_the_shared_module_is_missing(tmp_path, command):
    copy = tmp_path / "hooks"
    copy.mkdir()
    (copy / "block-dangerous-rm.py").write_text((HOOKS / "block-dangerous-rm.py").read_text())
    payload = {"tool_name": "Bash", "tool_input": {"command": command}}
    assert '"deny"' in run_hook("block-dangerous-rm.py", payload, tmp_path, hooks=copy)


def test_the_rm_hook_still_denies_when_the_shared_module_is_missing(tmp_path):
    copy = tmp_path / "hooks"
    copy.mkdir()
    (copy / "block-dangerous-rm.py").write_text((HOOKS / "block-dangerous-rm.py").read_text())
    rm = {"tool_name": "Bash", "tool_input": {"command": "rm -rf /tmp/x"}}
    ls = {"tool_name": "Bash", "tool_input": {"command": "ls"}}
    assert '"deny"' in run_hook("block-dangerous-rm.py", rm, tmp_path, hooks=copy)
    assert run_hook("block-dangerous-rm.py", ls, tmp_path, hooks=copy) == ""


@pytest.mark.parametrize("payload", [[], "x", None, {"tool_name": "Bash", "tool_input": "x"}, {"tool_name": "Bash", "tool_input": {"command": "git status"}, "cwd": 5}])
def test_malformed_payloads_do_not_crash_the_allow_hook(tmp_path, payload):
    assert run_hook("allow-compound-bash.py", payload, tmp_path) == ""
