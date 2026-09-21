import subprocess
from datetime import UTC, datetime

import pytest
from dotfiles_backup import build_arg_parser, main


def test_aborts_when_flaky_it_sync_fails():
    calls = []

    def run(argv, cwd=None, **kwargs):
        calls.append(argv)
        if "sync-hunt-flaky-it.sh" in argv[0]:
            return subprocess.CompletedProcess(argv, 1)
        return subprocess.CompletedProcess(argv, 0)

    assert main(["save"], run=run) == 1
    assert len(calls) == 1


def test_aborts_when_machine_paths_invalid(capsys):
    def run(argv, cwd=None, **kwargs):
        if "validate-no-machine-paths.sh" in argv[0]:
            return subprocess.CompletedProcess(argv, 1)
        return subprocess.CompletedProcess(argv, 0)

    assert main(["save"], run=run) == 1
    assert "Aborting" in capsys.readouterr().err


def FIXED_NOW():
    return datetime(2026, 9, 21, 12, 30, 45, tzinfo=UTC)


def fake_run(calls=None, branch="main", dirty=True, fail=None, has_pr=False):
    def run(argv, cwd=None, **kwargs):
        if calls is not None:
            calls.append(argv)
        if fail and argv[:2] == fail:
            return subprocess.CompletedProcess(argv, 1)
        if argv[:3] == ["git", "status", "--porcelain"]:
            out = " M zsh/.zshrc\n" if dirty and "--" not in argv else ""
            return subprocess.CompletedProcess(argv, 0, stdout=out)
        if argv[:3] == ["gh", "pr", "view"]:
            return subprocess.CompletedProcess(argv, 0 if has_pr else 1)
        if argv[:2] == ["git", "branch"]:
            return subprocess.CompletedProcess(argv, 0, stdout=f"{branch}\n")
        return subprocess.CompletedProcess(argv, 0)

    return run


def test_from_main_creates_backup_branch_pushes_it_and_opens_pr(capsys):
    calls = []

    assert main(["save"], run=fake_run(calls), now=FIXED_NOW) == 0
    assert [c for c in calls if c[:3] != ["gh", "pr", "view"]][-5:] == [
        ["git", "switch", "-c", "backup/20260921-123045"],
        ["git", "add", "."],
        ["git", "commit", "-m", "chore: update configs and package lists"],
        ["git", "push", "-u", "origin", "backup/20260921-123045"],
        ["gh", "pr", "create", "--base", "main", "--fill"],
    ]
    assert "Dotfiles backup complete." in capsys.readouterr().out


def test_never_pushes_to_main():
    calls = []

    main(["save"], run=fake_run(calls), now=FIXED_NOW)
    assert ["git", "push"] not in calls
    assert not any(c[:2] == ["git", "push"] and c[-1] == "main" for c in calls)


def test_reuses_existing_feature_branch():
    calls = []

    assert main(["save"], run=fake_run(calls, branch="backup/earlier"), now=FIXED_NOW) == 0
    assert not any(c[:2] == ["git", "switch"] for c in calls)
    assert ["git", "push", "-u", "origin", "backup/earlier"] in calls


def test_nothing_to_back_up_makes_no_commit(capsys):
    calls = []

    assert main(["save"], run=fake_run(calls, dirty=False), now=FIXED_NOW) == 0
    assert not any(c[:2] == ["git", "commit"] for c in calls)
    assert "Nothing to back up." in capsys.readouterr().out


def test_existing_pr_is_not_recreated(capsys):
    calls = []

    assert main(["save"], run=fake_run(calls, branch="backup/earlier", has_pr=True), now=FIXED_NOW) == 0
    assert ["git", "push", "-u", "origin", "backup/earlier"] in calls
    assert not any(c[:3] == ["gh", "pr", "create"] for c in calls)


@pytest.mark.parametrize(
    "failing", [["git", "switch"], ["git", "commit"], ["git", "push"], ["gh", "pr"]]
)
def test_aborts_when_a_git_step_fails(failing, capsys):
    assert main(["save"], run=fake_run(fail=failing), now=FIXED_NOW) == 1
    assert "Aborting" in capsys.readouterr().err


def test_aborts_when_claude_settings_have_uncommitted_changes(capsys):
    def run(argv, cwd=None, **kwargs):
        if argv[:2] == ["git", "status"]:
            return subprocess.CompletedProcess(
                argv, 0, stdout=" M claude/.claude/settings.json\n"
            )
        return subprocess.CompletedProcess(argv, 0)

    assert main(["save"], run=run) == 1
    assert "claude-settings-split" in capsys.readouterr().err


def test_proceeds_when_claude_settings_are_clean(capsys):
    assert main(["save"], run=fake_run(), now=FIXED_NOW) == 0
    assert "Dotfiles backup complete." in capsys.readouterr().out


def test_main_without_command_prints_help_and_returns_1(capsys):
    assert main([]) == 1
    out = capsys.readouterr().out
    assert "usage:" in out
    assert "save" in out


def test_top_level_help_lists_save_subcommand_and_examples(capsys):
    parser = build_arg_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["-h"])
    out = capsys.readouterr().out
    assert "save" in out
    assert "Examples:" in out
    assert "dotfiles-backup save" in out
