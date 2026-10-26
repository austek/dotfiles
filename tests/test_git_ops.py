import subprocess
from pathlib import Path

import git_ops


def _runner(stdout="", returncode=0, calls=None):
    def run(argv, **kwargs):
        if calls is not None:
            calls.append((argv, kwargs.get("cwd")))
        return subprocess.CompletedProcess(argv, returncode, stdout=stdout)

    return run


def test_has_changes_true_for_porcelain_output():
    assert git_ops.has_changes(Path("/r"), run=_runner(" M a\n")) is True


def test_has_changes_false_for_blank_or_none_output():
    assert git_ops.has_changes(Path("/r"), run=_runner("  \n")) is False
    assert git_ops.has_changes(Path("/r"), run=_runner(None)) is False


def test_claude_settings_changed_scopes_status_to_settings_file():
    calls = []
    assert git_ops.claude_settings_changed(Path("/r"), run=_runner(" M x", calls=calls)) is True
    assert calls == [(["git", "status", "--porcelain", "--", "claude/.claude/settings.json"], Path("/r"))]


def test_current_branch_strips_output():
    assert git_ops.current_branch(Path("/r"), run=_runner("feature/x\n")) == "feature/x"


def test_create_branch_reports_exit_status():
    assert git_ops.create_branch(Path("/r"), "b", run=_runner(returncode=0)) is True
    assert git_ops.create_branch(Path("/r"), "b", run=_runner(returncode=1)) is False


def test_pr_exists_reflects_gh_exit_status():
    assert git_ops.pr_exists(Path("/r"), "b", run=_runner(returncode=0)) is True
    assert git_ops.pr_exists(Path("/r"), "b", run=_runner(returncode=1)) is False
