import subprocess

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


def test_commits_and_pushes_on_success(capsys):
    calls = []

    def run(argv, cwd=None, **kwargs):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0)

    assert main(["save"], run=run) == 0
    assert calls[-3] == ["git", "add", "."]
    assert calls[-2][:2] == ["git", "commit"]
    assert calls[-1] == ["git", "push"]
    assert "Dotfiles backup complete." in capsys.readouterr().out


def test_completes_even_if_git_commit_fails(capsys):
    def run(argv, cwd=None, **kwargs):
        if argv[:2] == ["git", "commit"]:
            return subprocess.CompletedProcess(argv, 1)
        return subprocess.CompletedProcess(argv, 0)

    assert main(["save"], run=run) == 0
    assert "Dotfiles backup complete." in capsys.readouterr().out


def test_completes_even_if_git_push_fails(capsys):
    def run(argv, cwd=None, **kwargs):
        if argv[:2] == ["git", "push"]:
            return subprocess.CompletedProcess(argv, 1)
        return subprocess.CompletedProcess(argv, 0)

    assert main(["save"], run=run) == 0
    assert "Dotfiles backup complete." in capsys.readouterr().out


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
    def run(argv, cwd=None, **kwargs):
        if argv[:2] == ["git", "status"]:
            return subprocess.CompletedProcess(argv, 0, stdout="")
        return subprocess.CompletedProcess(argv, 0)

    assert main(["save"], run=run) == 0
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
