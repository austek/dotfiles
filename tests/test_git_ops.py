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


def test_status_failed_reflects_exit_status():
    assert git_ops.status_failed(Path("/r"), run=_runner(returncode=128)) is True
    assert git_ops.status_failed(Path("/r"), run=_runner(returncode=0)) is False


def test_claude_settings_changed_scopes_status_to_settings_file():
    calls = []
    assert git_ops.claude_settings_changed(Path("/r"), run=_runner(" M x", calls=calls)) is True
    assert calls == [(["git", "status", "--porcelain", "--", "claude/.claude/settings.json"], Path("/r"))]


def test_current_branch_strips_output():
    assert git_ops.current_branch(Path("/r"), run=_runner("feature/x\n")) == "feature/x"


def test_create_branch_reports_exit_status():
    assert git_ops.create_branch(Path("/r"), "b", run=_runner(returncode=0)) is True
    assert git_ops.create_branch(Path("/r"), "b", run=_runner(returncode=1)) is False


def _rev_parse_runner(answers, calls=None):
    def run(argv, **kwargs):
        if calls is not None:
            calls.append(argv)
        key = ("abs" if "--path-format=absolute" in argv else "rel", argv[-1])
        out = answers.get(key)
        return subprocess.CompletedProcess(argv, 0 if out is not None else 128, stdout=out or "")

    return run


def test_in_worktree_false_when_git_dir_equals_common_dir():
    answers = {("abs", "--git-common-dir"): "/r/.git", ("abs", "--git-dir"): "/r/.git"}
    assert git_ops.in_worktree(Path("/r"), run=_rev_parse_runner(answers)) is False


def test_in_worktree_true_when_git_dir_differs_from_common_dir():
    answers = {("abs", "--git-common-dir"): "/r/.git", ("abs", "--git-dir"): "/r/.git/worktrees/w"}
    assert git_ops.in_worktree(Path("/r"), run=_rev_parse_runner(answers)) is True


def test_in_worktree_falls_back_to_relative_paths_when_flag_is_rejected():
    answers = {("rel", "--git-common-dir"): ".git", ("rel", "--git-dir"): ".git"}
    calls = []
    assert git_ops.in_worktree(Path("/r"), run=_rev_parse_runner(answers, calls)) is False
    assert ["git", "rev-parse", "--git-dir"] in calls


def test_in_worktree_fallback_detects_linked_worktree():
    answers = {("rel", "--git-common-dir"): "/r/.git", ("rel", "--git-dir"): "/r/.git/worktrees/w"}
    assert git_ops.in_worktree(Path("/r"), run=_rev_parse_runner(answers)) is True


def test_in_worktree_true_when_rev_parse_fails_entirely():
    assert git_ops.in_worktree(Path("/r"), run=_rev_parse_runner({})) is True


def test_untracked_files_lists_ls_files_output():
    calls = []
    assert git_ops.untracked_files(Path("/r"), run=_runner("a\nb/c\n", calls=calls)) == ["a", "b/c"]
    assert calls == [(["git", "ls-files", "--others", "--exclude-standard"], Path("/r"))]


def test_untracked_files_empty_when_none():
    assert git_ops.untracked_files(Path("/r"), run=_runner("")) == []


def test_pr_exists_reflects_gh_exit_status():
    assert git_ops.pr_exists(Path("/r"), "b", run=_runner(returncode=0)) is True
    assert git_ops.pr_exists(Path("/r"), "b", run=_runner(returncode=1)) is False
