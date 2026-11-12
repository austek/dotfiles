"""Tests for claude/.claude/hooks/block-dangerous-rm.py."""
import sys

sys.dont_write_bytecode = True  # keep __pycache__ out of the stowed hooks package

import contextlib
import importlib.util
import io
import json
from pathlib import Path

import pytest

HOOK_DIR = Path(__file__).resolve().parent.parent / "claude" / ".claude" / "hooks"
SETTINGS = HOOK_DIR.parent / "settings.json"
HOOK_PATH = HOOK_DIR / "block-dangerous-rm.py"

_spec = importlib.util.spec_from_file_location("block_dangerous_rm", HOOK_PATH)
hook = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(hook)


DENY = [
    "rm -rf /",
    "rm -rf /*",
    "rm -rf ~",
    "rm -rf ~/",
    "rm -rf ~/*",
    "rm -rf $HOME",
    "rm -rf ${HOME}/*",
    "rm -rf /etc",
    "rm -rf /usr/",
    "rm -rf /home",
    "rm -rf /root",
    "rm -rf /var",
    "rm -rf ..",
    "rm -rf ../*",
    "rm -fr /",
    "rm -Rf /",
    "rm -r -f /",
    "rm --recursive --force /",
    "sudo rm -rf /",
    "rm -rf $SOME_DIR",
    "rm -rf $SOME_DIR/*",
    "rm -rf ${SOME_DIR:-}/*",
    "rm -rf $1",
    "rm -rf $@",
    "cd /tmp && rm -rf /",
    "true; rm -rf /etc",
    "echo hi | rm -rf $HOME",
    "/bin/rm -rf /",
    "/usr/bin/rm -rf /home",
    "sudo /bin/rm -rf /",
    "echo a#b; rm -rf /",
    'bash -c "rm -rf /"',
    'sh -c "rm -rf $HOME"',
    'eval "rm -rf /"',
    "ssh host 'rm -rf /etc'",
    "rm -rf //",
    "rm -rf /etc/.",
    "rm -rf ~/.",
    "rm -rf ../..",
    "rm -rf $A/$B",
    "rm -rf /e*",
    "rm -rf /sbin",
    "rm -rf /home/user",
    "rm -rf /tmp/../etc",
    "rm --rec --forc /",
    'rm -rf "/unclosed',
    "echo / | xargs rm -rf",
    "xargs -a list rm -rf",
    "rm -rf $(cat x)",
    "rm -rf `cat x`",
    "rm -rf $(pwd)/..",
    "rm -rf $'/'",
    "rm -rf $TMPDIR/../..",
    "rm -rf /tmp/$X",
    "find / -exec rm -rf {} \\;",
    "find ~ -exec rm -rf {} ';'",
    "find /etc -execdir rm -rf {} +",
    "find / -ok rm -rf {} \\;",
    "find / -delete",
    "find $HOME -delete",
    "find /tmp -exec rm -rf $X \\;",
    "find /tmp -exec sh -c 'rm -rf /' \\;",
    "find -L / -delete",
    "find -H -D tree / -delete",
    "sudo find / -delete",
    "sudo -u root find / -exec rm -rf {} \\;",
    "rtk find ~ -delete",
    "FOO=1 find / -delete",
    "timeout 5 find / -delete",
    "( find / -delete )",
]

ALLOW = [
    "rm -rf /tmp/build",
    "rm -rf /tmp",
    "rm -rf /var/tmp/cache",
    "rm -rf $TMPDIR/x",
    "rm -rf ~/scratchpad",
    "rm -rf ./node_modules",
    "rm -rf /home/user/project/build",
    "rm -rf target",
    "ls -la /",
    "git status",
    # quoted text is one token, so its contents are never read as path/flag tokens
    "echo 'rm -rf /'",
    'gh api -f body="do not run rm -rf / here"',
    "echo 'unclosed",
    "/bin/rm -rf /tmp/build",
    "find /tmp/build -exec rm -rf {} \\;",
    "find . -name '*.pyc' -delete",
    "find / -exec grep x {} +",
]


@pytest.mark.parametrize("cmd", DENY)
def test_rule041_risky_recursive_deletes_are_denied(cmd):
    verdict = hook.check(cmd)
    assert verdict is not None, "expected a deny verdict"
    assert json.loads(verdict)["hookSpecificOutput"]["permissionDecision"] == "deny"


@pytest.mark.parametrize("cmd", ALLOW)
def test_rule041_safe_commands_get_no_verdict(cmd):
    assert hook.check(cmd) is None, "expected no verdict"


def test_rule041_requires_both_r_and_f():
    assert hook.check("rm -r /") is None
    assert hook.check("rm -f /") is None


def run_main(monkeypatch, payload):
    out = io.StringIO()
    monkeypatch.setattr(hook.sys, "stdin", io.StringIO(json.dumps(payload)))
    with contextlib.redirect_stdout(out):
        rc = hook.main()
    return rc, out.getvalue().strip()


@pytest.mark.parametrize("tool", sorted(hook.GUARDED_TOOLS))
def test_every_guarded_tool_is_checked(monkeypatch, tool):
    rc, out = run_main(monkeypatch, {"tool_name": tool, "tool_input": {"command": "rm -rf /"}})
    assert rc == 0
    assert "permissionDecision" in out, f"{tool} in GUARDED_TOOLS but not blocked"


def test_unguarded_tool_ignored(monkeypatch):
    rc, out = run_main(monkeypatch, {"tool_name": "Read", "tool_input": {"command": "rm -rf /"}})
    assert (rc, out) == (0, "")


def test_program_arguments_field_checked(monkeypatch):
    _rc, out = run_main(monkeypatch, {
        "tool_name": "mcp__idea__execute_run_configuration",
        "tool_input": {"programArguments": "rm -rf /"},
    })
    assert "permissionDecision" in out


@pytest.mark.parametrize("payload", [
    {}, {"tool_name": "Bash"}, {"tool_name": "Bash", "tool_input": None},
    {"tool_name": "Bash", "tool_input": {"command": None}},
    {"tool_name": "Bash", "tool_input": {"command": ""}},
])
def test_malformed_input_never_crashes(monkeypatch, payload):
    assert run_main(monkeypatch, payload) == (0, "")


def test_settings_matchers_equal_guarded_tools():
    """Drift is silent both ways: a matcher missing from GUARDED_TOOLS fires the hook without checking, and a tool with no matcher never invokes it."""
    settings = json.loads(SETTINGS.read_text())
    matched = set()
    for group in settings.get("hooks", {}).get("PreToolUse", []):
        commands = [h.get("command", "") for h in group.get("hooks", [])]
        if not any(HOOK_PATH.name in c for c in commands):
            continue
        matched.update(group.get("matcher", "").split("|"))
    assert matched == hook.GUARDED_TOOLS
