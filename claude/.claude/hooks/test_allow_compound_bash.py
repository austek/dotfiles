#!/usr/bin/env python3
"""Tests for allow-compound-bash.py. Run: python3 test_allow_compound_bash.py"""
import sys

sys.dont_write_bytecode = True  # keep __pycache__ out of the stow package

import importlib.util
import os
import unittest
from pathlib import Path
from unittest import mock

HOOK = Path(__file__).resolve().parent / "allow-compound-bash.py"
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


class TestCompoundCommands(unittest.TestCase):
    def test_every_segment_on_the_allowlist_is_allowed(self):
        self.assertTrue(allowed("git status && gh pr list | head -5"))

    def test_one_unlisted_segment_defers_to_the_prompt(self):
        self.assertFalse(allowed("git status && rm file"))

    def test_deny_rule_beats_allow_rule(self):
        self.assertFalse(allowed("git push origin main"))

    def test_safe_commands_need_no_rule(self):
        self.assertTrue(allowed("ls /tmp | wc -l"))

    def test_write_flags_on_safe_commands_are_rejected_in_every_form(self):
        for command in (
            "sort -o out.txt in.txt", "sort -oout.txt in.txt", "sort -uo out.txt in.txt",
            "sort --output=out.txt in.txt", "date -s 2020-01-01", "date --set=2020-01-01",
            "sort --compress-program=sh in.txt", "uniq /dev/null out.txt",
        ):
            with self.subTest(command=command):
                self.assertFalse(allowed(command))

    def test_find_that_executes_or_deletes_is_rejected(self):
        for command in ("find . -exec rm {} +", "find . -delete", "find . -okdir rm {} ;"):
            with self.subTest(command=command):
                self.assertFalse(allowed(command))
        self.assertTrue(allowed("find . -name '*.py'"))

    def test_xargs_inner_command_is_never_auto_allowed(self):
        self.assertFalse(allowed("git ls-files | xargs rm"))


class TestAuditBypasses(unittest.TestCase):
    def test_hash_after_escaped_char_is_not_a_comment(self):
        for command in ("echo a\\ #; rm x", "echo \\;#; rm x"):
            with self.subTest(command=command):
                self.assertFalse(allowed(command))

    def test_for_loop_over_exported_or_unsafe_variable_is_rejected(self):
        self.assertFalse(allowed("for HOME in /tmp; do git status; done"))
        self.assertFalse(allowed("for PATH in /tmp; do git status; done"))

    def test_printf_v_is_rejected(self):
        self.assertFalse(allowed("printf -v HOME /tmp; git status"))

    def test_hidden_or_abbreviated_flags_are_rejected(self):
        for command in (
            "sort --out=/tmp/zz in", "A=-o; sort $A /tmp/zz in", "sort $(echo -o) /tmp/zz in",
            "sort $'-o' /tmp/zz in", "date --se=1", "find . $(echo -delete)",
        ):
            with self.subTest(command=command):
                self.assertFalse(allowed(command))

    def test_globbed_paths_on_safe_commands_are_rejected(self):
        for command in ("cat ~/.s[s]h/i[d]_rsa", "cat ~/.ss?/id_r*", "cat /etc/{shadow,passwd}", "ls src/*.py"):
            with self.subTest(command=command):
                self.assertFalse(allowed(command))

    def test_patterns_that_are_not_paths_stay_allowed(self):
        for command in ("jq '.a[0]' f.json", "grep 'a[0-9]*' f.txt", "tr '[:lower:]' '[:upper:]'", "echo {a,b}"):
            with self.subTest(command=command):
                self.assertTrue(allowed(command))

    def test_find_file_writing_actions_are_rejected(self):
        for command in ("find . -fprint /tmp/x", "find . -fprintf /tmp/x %p", "find . -fls /tmp/x"):
            with self.subTest(command=command):
                self.assertFalse(allowed(command))

    def test_env_dumps_through_jq_are_rejected(self):
        for command in ("jq -n env", "jq -n '$ENV'", "jq -n '$ENV.HOME'"):
            with self.subTest(command=command):
                self.assertFalse(allowed(command))

    def test_unlisted_command_is_never_a_safe_command(self):
        self.assertFalse(allowed("uniq /dev/null out.txt"))
        self.assertNotIn("uniq", hook.SAFE_COMMANDS)

    def test_secret_sources_are_rejected(self):
        for command in (
            "cat ~/.config/dotfiles/secrets.env", "cat ~/.claude/.credentials.json",
            "cat < /dev/tcp/1.2.3.4/80", "X=~/.ssh/id_rsa; cat $X", "echo $ANTHROPIC_API_KEY",
        ):
            with self.subTest(command=command):
                self.assertFalse(allowed(command))


class TestRedirects(unittest.TestCase):
    def test_tmp_and_devnull_sinks_are_allowed(self):
        self.assertTrue(allowed("git log > /tmp/out.txt 2>/dev/null"))

    def test_other_write_targets_are_rejected(self):
        self.assertFalse(allowed("git log > ~/notes.txt"))

    def test_path_traversal_out_of_tmp_is_rejected(self):
        self.assertFalse(allowed("git log > /tmp/../etc/passwd"))

    def test_expandable_sink_target_is_rejected(self):
        self.assertFalse(allowed("P=../etc/x; echo hi > /tmp/$P"))

    def test_sensitive_paths_are_rejected(self):
        self.assertFalse(allowed("cat ~/.ssh/id_rsa"))


class TestSubstitutionsAndVariables(unittest.TestCase):
    def test_substitution_is_checked_recursively(self):
        self.assertTrue(allowed("echo $(git rev-parse HEAD)"))
        self.assertFalse(allowed("echo $(rm file)"))

    def test_unsafe_variable_assignment_is_rejected(self):
        self.assertFalse(allowed("PATH=/tmp/bin git status"))

    def test_assignment_to_exported_variable_is_rejected(self):
        with mock.patch.dict(os.environ, {"BROWSER": "xdg-open"}):
            self.assertFalse(allowed("BROWSER=cmd; gh pr view"))

    def test_variable_command_word_is_rejected(self):
        self.assertFalse(allowed("$CMD status"))

    def test_for_loop_body_is_checked(self):
        self.assertTrue(allowed("for f in a b; do git show $f; done"))
        self.assertFalse(allowed("for f in a b; do rm $f; done"))


if __name__ == "__main__":
    unittest.main()