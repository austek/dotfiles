#!/usr/bin/env python3
"""Tests for block-dangerous-rm.py. Run: python3 test_block_dangerous_rm.py"""
import sys

sys.dont_write_bytecode = True  # keep __pycache__ out of the stow package

import contextlib
import importlib.util
import io
import json
import unittest
import unittest.mock
from pathlib import Path

HOOK_DIR = Path(__file__).resolve().parent
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
    # unbalanced quotes: unparseable, so deliberately not blocked
    "rm -rf \"/unclosed",
    "/bin/rm -rf /tmp/build",
]


class TestVerdicts(unittest.TestCase):
    def test_denied(self):
        for cmd in DENY:
            with self.subTest(cmd=cmd):
                verdict = hook.check(cmd)
                self.assertIsNotNone(verdict, "expected a deny verdict")
                payload = json.loads(verdict)["hookSpecificOutput"]
                self.assertEqual(payload["permissionDecision"], "deny")

    def test_allowed(self):
        for cmd in ALLOW:
            with self.subTest(cmd=cmd):
                self.assertIsNone(hook.check(cmd), "expected no verdict")

    def test_requires_both_r_and_f(self):
        self.assertIsNone(hook.check("rm -r /"))
        self.assertIsNone(hook.check("rm -f /"))


def run_main(payload):
    out = io.StringIO()
    stdin = io.StringIO(json.dumps(payload))
    with contextlib.redirect_stdout(out), unittest.mock.patch.object(hook.sys, "stdin", stdin):
        rc = hook.main()
    return rc, out.getvalue().strip()


class TestToolGate(unittest.TestCase):
    def test_every_guarded_tool_is_checked(self):
        for tool in hook.GUARDED_TOOLS:
            with self.subTest(tool=tool):
                rc, out = run_main({"tool_name": tool, "tool_input": {"command": "rm -rf /"}})
                self.assertEqual(rc, 0)
                self.assertIn("permissionDecision", out, f"{tool} in GUARDED_TOOLS but not blocked")

    def test_unguarded_tool_ignored(self):
        rc, out = run_main({"tool_name": "Read", "tool_input": {"command": "rm -rf /"}})
        self.assertEqual((rc, out), (0, ""))

    def test_program_arguments_field_checked(self):
        _rc, out = run_main({
            "tool_name": "mcp__idea__execute_run_configuration",
            "tool_input": {"programArguments": "rm -rf /"},
        })
        self.assertIn("permissionDecision", out)

    def test_malformed_input_never_crashes(self):
        for payload in ({}, {"tool_name": "Bash"}, {"tool_name": "Bash", "tool_input": None},
                        {"tool_name": "Bash", "tool_input": {"command": None}},
                        {"tool_name": "Bash", "tool_input": {"command": ""}}):
            with self.subTest(payload=payload):
                self.assertEqual(run_main(payload), (0, ""))


class TestSettingsInSync(unittest.TestCase):
    """GUARDED_TOOLS and the settings.json matchers must agree exactly.

    Drift is silent in both directions: a matcher missing from GUARDED_TOOLS makes
    the hook fire and return 0 without checking, and a tool in GUARDED_TOOLS with
    no matcher means the hook is never invoked for it.
    """

    def test_matchers_equal_guarded_tools(self):
        settings = json.loads(SETTINGS.read_text())
        matched = set()
        for group in settings.get("hooks", {}).get("PreToolUse", []):
            commands = [h.get("command", "") for h in group.get("hooks", [])]
            if not any(HOOK_PATH.name in c for c in commands):
                continue
            matched.update(group.get("matcher", "").split("|"))
        self.assertEqual(matched, hook.GUARDED_TOOLS)


if __name__ == "__main__":
    unittest.main(verbosity=2)
