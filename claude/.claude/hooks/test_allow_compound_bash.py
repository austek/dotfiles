#!/usr/bin/env python3
"""Tests for allow-compound-bash.py. Run: python3 test_allow_compound_bash.py"""
import sys

sys.dont_write_bytecode = True  # keep __pycache__ out of the stow package

import importlib.util
import unittest
from pathlib import Path

HOOK = Path(__file__).resolve().parent / "allow-compound-bash.py"
spec = importlib.util.spec_from_file_location("allow_compound_bash", HOOK)
hook = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hook)

RULES = {
    "allow": [hook.to_regex(p) for p in ("git *", "gh *", "./gradlew *test*")],
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

    def test_unsafe_flag_on_safe_command_is_rejected(self):
        self.assertFalse(allowed("sort -o out.txt in.txt"))


class TestRedirects(unittest.TestCase):
    def test_tmp_and_devnull_sinks_are_allowed(self):
        self.assertTrue(allowed("git log > /tmp/out.txt 2>/dev/null"))

    def test_other_write_targets_are_rejected(self):
        self.assertFalse(allowed("git log > ~/notes.txt"))

    def test_path_traversal_out_of_tmp_is_rejected(self):
        self.assertFalse(allowed("git log > /tmp/../etc/passwd"))

    def test_sensitive_paths_are_rejected(self):
        self.assertFalse(allowed("cat ~/.ssh/id_rsa"))


class TestSubstitutionsAndVariables(unittest.TestCase):
    def test_substitution_is_checked_recursively(self):
        self.assertTrue(allowed("echo $(git rev-parse HEAD)"))
        self.assertFalse(allowed("echo $(rm file)"))

    def test_unsafe_variable_assignment_is_rejected(self):
        self.assertFalse(allowed("PATH=/tmp/bin git status"))

    def test_variable_command_word_is_rejected(self):
        self.assertFalse(allowed("$CMD status"))

    def test_for_loop_body_is_checked(self):
        self.assertTrue(allowed("for f in a b; do git show $f; done"))
        self.assertFalse(allowed("for f in a b; do rm $f; done"))


if __name__ == "__main__":
    unittest.main()