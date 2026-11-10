import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest
from dotfiles_backup import build_arg_parser, main


@pytest.fixture(autouse=True)
def no_overlay(monkeypatch, tmp_path):
    monkeypatch.setenv("DOTFILES_PRIVATE_ROOT", str(tmp_path / "absent"))


@pytest.fixture
def private_repo(monkeypatch, tmp_path):
    root = tmp_path / "private"
    (root / ".git").mkdir(parents=True)
    monkeypatch.setenv("DOTFILES_PRIVATE_ROOT", str(root))
    return root


def test_backs_up_private_overlay_in_its_own_repo(private_repo):
    calls = []

    def run(argv, cwd=None, **kwargs):
        calls.append((argv, cwd))
        return fake_run()(argv, cwd=cwd, **kwargs)

    assert main(["save"], run=run, now=fixed_now) == 0
    private = [argv for argv, cwd in calls if cwd == private_repo]
    assert ["git", "commit", "-m", COMMIT] in private
    assert ["gh", "pr", "create", "--base", "main", "--fill"] in private
    assert ["git", "add", "."] in private
    assert not any("validate-no-machine-paths.sh" in argv[0] for argv in private)


def test_private_backup_runs_after_public_failure(private_repo, capsys):
    cwds = []

    def run(argv, cwd=None, **kwargs):
        cwds.append(cwd)
        return fake_run(fail=["git", "commit"] if cwd != private_repo else None)(argv, cwd=cwd, **kwargs)

    assert main(["save"], run=run, now=fixed_now) == 1
    assert private_repo in cwds


def test_private_backup_runs_after_public_exception(private_repo, capsys):
    cwds = []

    def run(argv, cwd=None, **kwargs):
        cwds.append(cwd)
        if cwd != private_repo and argv[:2] == ["git", "commit"]:
            raise FileNotFoundError("git")
        return fake_run()(argv, cwd=cwd, **kwargs)

    assert main(["save"], run=run, now=fixed_now) == 1
    assert private_repo in cwds
    assert "failed" in capsys.readouterr().err


def test_git_status_failure_aborts_instead_of_reporting_clean(capsys):
    def run(argv, cwd=None, **kwargs):
        if argv[:2] == ["git", "rev-parse"]:
            return rev_parse_answer(argv)
        code = 128 if argv[:2] == ["git", "status"] and "--" not in argv else 0
        return subprocess.CompletedProcess(argv, code, stdout="")

    assert main(["save"], run=run, now=fixed_now) == 1
    captured = capsys.readouterr()
    assert "git status" in captured.err
    assert "Nothing to back up" not in captured.out


def test_overlay_without_git_dir_is_skipped(monkeypatch, tmp_path):
    root = tmp_path / "bare"
    root.mkdir()
    monkeypatch.setenv("DOTFILES_PRIVATE_ROOT", str(root))
    cwds = []

    def run(argv, cwd=None, **kwargs):
        cwds.append(cwd)
        return fake_run()(argv, cwd=cwd, **kwargs)

    assert main(["save"], run=run, now=fixed_now) == 0
    assert root not in cwds


def test_aborts_when_machine_paths_invalid(capsys):
    def run(argv, cwd=None, **kwargs):
        if argv[:2] == ["git", "rev-parse"]:
            return rev_parse_answer(argv)
        if "validate-no-machine-paths.sh" in argv[0]:
            return subprocess.CompletedProcess(argv, 1)
        return subprocess.CompletedProcess(argv, 0)

    assert main(["save"], run=run) == 1
    assert "Aborting" in capsys.readouterr().err


COMMIT = "chore: update configs and package lists NO_ISSUE"


def fixed_now():
    return datetime(2026, 9, 21, 12, 30, 45, tzinfo=UTC)


def rev_parse_answer(argv, linked=False):
    out = ".git"
    if linked and "--git-dir" in argv:
        out = ".git/worktrees/x"
    return subprocess.CompletedProcess(argv, 0, stdout=out + "\n")


def fake_run(
    calls=None, branch="main", dirty=True, fail=None, has_pr=False, untracked=(), linked=(), fail_validate=False
):
    def run(argv, cwd=None, **kwargs):
        if calls is not None:
            calls.append(argv)
        if argv[:2] == ["git", "rev-parse"]:
            return rev_parse_answer(argv, linked=cwd in linked)
        if argv[:3] == ["git", "ls-files", "--others"]:
            return subprocess.CompletedProcess(argv, 0, stdout="".join(f"{u}\n" for u in untracked))
        if fail_validate and argv[-1:] == ["--staged"]:
            return subprocess.CompletedProcess(argv, 1)
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

    assert main(["save"], run=fake_run(calls), now=fixed_now) == 0
    assert ["git", "switch", "-c", "backup/20260921-123045"] in calls
    assert ["git", "commit", "-m", COMMIT] in calls
    assert ["git", "push", "-u", "origin", "backup/20260921-123045"] in calls
    assert ["gh", "pr", "create", "--base", "main", "--fill"] in calls
    assert "Dotfiles backup complete." in capsys.readouterr().out


def index_of(calls, prefix):
    return next(i for i, c in enumerate(calls) if c[: len(prefix)] == prefix)


def test_stage_validates_staged_files_before_branch_commit_and_push():
    calls = []

    assert main(["save"], run=fake_run(calls), now=fixed_now) == 0
    order = [
        index_of(calls, ["git", "add", "."]),
        next(i for i, c in enumerate(calls) if c[0].endswith("validate-no-machine-paths.sh") and c[1:] == ["--staged"]),
        index_of(calls, ["git", "switch", "-c"]),
        index_of(calls, ["git", "commit"]),
        index_of(calls, ["git", "push"]),
    ]
    assert order == sorted(order)


def test_staged_validation_failure_resets_index_and_stops_before_branch(capsys):
    calls = []

    assert main(["save"], run=fake_run(calls, fail_validate=True), now=fixed_now) == 1
    assert ["git", "reset", "-q"] in calls
    assert index_of(calls, ["git", "add", "."]) < index_of(calls, ["git", "reset", "-q"])
    assert not any(c[:2] in (["git", "switch"], ["git", "commit"], ["git", "push"]) for c in calls)
    assert "Aborting" in capsys.readouterr().err


@pytest.mark.parametrize("failing", [["git", "add"], ["git", "switch"]])
def test_a_failed_add_or_branch_creation_resets_the_index(failing):
    calls = []

    assert main(["save"], run=fake_run(calls, fail=failing), now=fixed_now) == 1
    assert ["git", "reset", "-q"] in calls
    assert not any(c[:2] in (["git", "commit"], ["git", "push"]) for c in calls)


def test_overlay_flow_skips_staged_validation(private_repo):
    calls = []

    def run(argv, cwd=None, **kwargs):
        calls.append((argv, cwd))
        return fake_run()(argv, cwd=cwd, **kwargs)

    assert main(["save"], run=run, now=fixed_now) == 0
    assert not any(argv[-1:] == ["--staged"] and cwd == private_repo for argv, cwd in calls)


def test_lists_untracked_files_before_the_commit(capsys):
    calls = []

    def run(argv, cwd=None, **kwargs):
        if argv[:2] == ["git", "commit"]:
            assert "New untracked files being added (2):" in capsys.readouterr().out
        return fake_run(calls, untracked=["a.txt", "b/c.txt"])(argv, cwd=cwd, **kwargs)

    assert main(["save"], run=run, now=fixed_now) == 0
    assert ["git", "commit", "-m", COMMIT] in calls


def test_lists_untracked_files_of_the_overlay_too(private_repo, capsys):
    assert main(["save"], run=fake_run(untracked=["n.txt"]), now=fixed_now) == 0
    assert capsys.readouterr().out.count("New untracked files being added (1):") == 2


def test_prints_no_untracked_section_when_none(capsys):
    assert main(["save"], run=fake_run(), now=fixed_now) == 0
    assert "untracked" not in capsys.readouterr().out


def test_untracked_listing_is_capped_at_50(capsys):
    names = [f"f{i}.txt" for i in range(53)]

    assert main(["save"], run=fake_run(untracked=names), now=fixed_now) == 0
    out = capsys.readouterr().out
    assert "New untracked files being added (53):" in out
    assert "f49.txt" in out
    assert "f50.txt" not in out
    assert "... and 3 more" in out


def test_refuses_linked_worktree_without_mutating(tmp_path, capsys):
    calls = []
    public = Path(__file__).resolve().parent.parent

    assert main(["save"], run=fake_run(calls, linked={public}), now=fixed_now) == 1
    assert "main checkout" in capsys.readouterr().err
    assert not any(c[:2] in (["git", "add"], ["git", "commit"], ["git", "push"], ["git", "switch"]) for c in calls)


def test_overlay_worktree_aborts_only_the_overlay(private_repo, capsys):
    calls = []

    def run(argv, cwd=None, **kwargs):
        calls.append((argv, cwd))
        return fake_run(linked={private_repo})(argv, cwd=cwd, **kwargs)

    assert main(["save"], run=run, now=fixed_now) == 1
    assert "main checkout" in capsys.readouterr().err
    assert ["git", "commit", "-m", COMMIT] in [argv for argv, cwd in calls if cwd != private_repo]
    assert not any(argv[:2] in (["git", "add"], ["git", "commit"]) for argv, cwd in calls if cwd == private_repo)


def test_help_says_main_checkout_only(capsys):
    parser = build_arg_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["-h"])
    assert "main checkout" in capsys.readouterr().out.replace("\n", " ")


def test_never_pushes_to_main():
    calls = []

    main(["save"], run=fake_run(calls), now=fixed_now)
    pushes = [c for c in calls if c[:2] == ["git", "push"]]
    assert pushes
    assert not any(ref == "main" or ref.endswith(":main") for c in pushes for ref in c[2:])


def test_reuses_existing_feature_branch():
    calls = []

    assert main(["save"], run=fake_run(calls, branch="backup/earlier"), now=fixed_now) == 0
    assert not any(c[:2] == ["git", "switch"] for c in calls)
    assert ["git", "push", "-u", "origin", "backup/earlier"] in calls


def test_nothing_to_back_up_makes_no_commit(capsys):
    calls = []

    assert main(["save"], run=fake_run(calls, dirty=False), now=fixed_now) == 0
    assert not any(c[:2] == ["git", "commit"] for c in calls)
    assert "Nothing to back up." in capsys.readouterr().out


def test_existing_pr_is_not_recreated(capsys):
    calls = []

    assert main(["save"], run=fake_run(calls, branch="backup/earlier", has_pr=True), now=fixed_now) == 0
    assert ["git", "push", "-u", "origin", "backup/earlier"] in calls
    assert not any(c[:3] == ["gh", "pr", "create"] for c in calls)


@pytest.mark.parametrize(
    "failing", [["git", "switch"], ["git", "commit"], ["git", "push"], ["gh", "pr"]]
)
def test_aborts_when_a_git_step_fails(failing, capsys):
    assert main(["save"], run=fake_run(fail=failing), now=fixed_now) == 1
    assert "Aborting" in capsys.readouterr().err


def test_aborts_when_claude_settings_have_uncommitted_changes(capsys):
    def run(argv, cwd=None, **kwargs):
        if argv[:2] == ["git", "rev-parse"]:
            return rev_parse_answer(argv)
        if argv[:2] == ["git", "status"]:
            return subprocess.CompletedProcess(
                argv, 0, stdout=" M claude/.claude/settings.json\n"
            )
        return subprocess.CompletedProcess(argv, 0)

    assert main(["save"], run=run) == 1
    assert "claude-settings-split" in capsys.readouterr().err


def test_proceeds_when_claude_settings_are_clean(capsys):
    assert main(["save"], run=fake_run(), now=fixed_now) == 0
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
