import os
import subprocess
from pathlib import Path

import pytest
from dotfiles_setup import overlay, overlay_migrate, rollback, tools
from dotfiles_setup.log import Logger
from dotfiles_setup.rollback import RollbackLog


class Recorder:
    def __init__(self, returncodes=()):
        self.calls = []
        self.returncodes = list(returncodes)

    def __call__(self, argv, **kwargs):
        self.calls.append((list(argv), kwargs.get("cwd")))
        code = self.returncodes.pop(0) if self.returncodes else 0
        return subprocess.CompletedProcess(argv, code, "", "boom" if code else "")

    def stow_calls(self):
        return [call for call in self.calls if call[0][0] == "stow"]

    def git_calls(self):
        return [call for call in self.calls if call[0][0] == "git"]


@pytest.fixture
def env(tmp_path, monkeypatch):
    for variable in ("DOTFILES_OVERLAY_ROOT", "DOTFILES_PRIVATE_ROOT"):
        monkeypatch.delenv(variable, raising=False)
    home = tmp_path / "home"
    home.mkdir()
    legacy, new = home / ".dotfiles-private", home / ".dotfiles-overlay"
    monkeypatch.setattr(overlay, "LEGACY_OVERLAY_ROOT", legacy)
    monkeypatch.setattr(overlay, "DEFAULT_OVERLAY_ROOT", new)
    return home, legacy, new


def run_migration(home, recorder, dry_run=False):
    t = tools.Tooling(Logger(dry_run=dry_run, verbosity=1), home, run=recorder)
    log = RollbackLog(home / "rollback.log")
    return overlay_migrate.migrate_legacy_overlay(t, log), log


def make_overlay(root: Path, common=("zsh", "claude"), scoped=("claude-collibra",)):
    root.mkdir()
    (root / ".stow-packages").write_text("# comment\n" + "\n".join(common) + "\n")
    (root / ".stow-packages.work").write_text("\n".join(scoped) + "\n")
    for name in (*common, *scoped):
        (root / name).mkdir()
    (root / "marker").write_text("kept")


def packages_of(call) -> list[str]:
    return [arg for arg in call[0][3:] if not arg.startswith("-")]


def test_nothing_happens_without_a_legacy_overlay(env):
    home, _, new = env
    recorder = Recorder()
    ok, log = run_migration(home, recorder)
    assert (ok, recorder.calls, log.entries(), new.exists()) == (True, [], [], False)


def test_the_overlay_is_unstowed_moved_relinked_and_the_move_is_recorded(env):
    home, legacy, new = env
    make_overlay(legacy)
    recorder = Recorder()
    ok, log = run_migration(home, recorder)
    assert ok
    delete, restow = recorder.stow_calls()
    assert delete[0][:3] == ["stow", "--delete", f"--target={home}"]
    assert (delete[1], packages_of(delete)) == (legacy, ["claude", "claude-collibra", "zsh"])
    assert restow[0][:3] == ["stow", "--restow", "--no-folding"]
    assert (restow[1], packages_of(restow)) == (new, ["claude", "claude-collibra", "zsh"])
    assert not legacy.exists()
    assert (new / "marker").read_text() == "kept"
    assert log.entries() == [f"OVERLAY_MOVED:{legacy}|{new}"]


def test_every_stow_packages_file_of_a_preset_is_read(env):
    home, legacy, _ = env
    legacy.mkdir()
    for name, text in ((".stow-packages", "zsh\n"), (".stow-packages.homelab", "k8s\n"), (".stow-packages.work", "zsh\nclaude-collibra\n")):
        (legacy / name).write_text(text)
    for package in ("zsh", "k8s", "claude-collibra"):
        (legacy / package).mkdir()
    recorder = Recorder()
    run_migration(home, recorder)
    assert packages_of(recorder.stow_calls()[0]) == ["claude-collibra", "k8s", "zsh"]


def test_editor_backups_of_the_package_files_are_not_read(env):
    home, legacy, _ = env
    make_overlay(legacy)
    (legacy / ".stow-packages.work~").write_text("ghost\n")
    (legacy / ".stow-packages.orig.bak").write_text("ghost\n")
    (legacy / "ghost").mkdir()
    recorder = Recorder()
    run_migration(home, recorder)
    assert "ghost" not in packages_of(recorder.stow_calls()[0])


def test_a_package_without_a_directory_is_skipped_because_stow_refuses_the_whole_call(env):
    home, legacy, _ = env
    make_overlay(legacy)
    (legacy / ".stow-packages").write_text("zsh\nnot-there\nclaude\n")
    recorder = Recorder()
    run_migration(home, recorder)
    assert packages_of(recorder.stow_calls()[0]) == ["claude", "claude-collibra", "zsh"]


def test_an_overlay_without_packages_is_just_moved(env):
    home, legacy, new = env
    legacy.mkdir()
    recorder = Recorder()
    ok, _ = run_migration(home, recorder)
    assert (ok, recorder.stow_calls(), new.is_dir(), legacy.exists()) == (True, [], True, False)


def test_a_failed_unstow_moves_nothing(env, capsys):
    home, legacy, new = env
    make_overlay(legacy)
    ok, log = run_migration(home, Recorder(returncodes=[1]))
    assert not ok
    assert legacy.is_dir() and not new.exists()
    assert log.entries() == []
    assert "boom" in capsys.readouterr().err


def test_a_failed_move_restows_the_overlay_from_where_it_was(env, monkeypatch):
    home, legacy, new = env
    make_overlay(legacy)

    def refuse(self, target):
        raise OSError("cross-device")

    monkeypatch.setattr(Path, "rename", refuse)
    recorder = Recorder()
    ok, log = run_migration(home, recorder)
    assert not ok
    _delete, restow = recorder.stow_calls()
    assert restow[0][:3] == ["stow", "--restow", "--no-folding"]
    assert restow[1] == legacy
    assert legacy.is_dir() and not new.exists()
    assert log.entries() == []


def test_a_failed_restow_after_the_move_warns_and_the_move_still_counts(env, capsys):
    home, legacy, new = env
    make_overlay(legacy)
    ok, log = run_migration(home, Recorder(returncodes=[0, 1]))
    assert ok
    assert new.is_dir()
    assert log.entries() == [f"OVERLAY_MOVED:{legacy}|{new}"]
    assert "Could not restow" in capsys.readouterr().out


def test_both_locations_present_unstows_the_old_links_and_keeps_both_directories(env, capsys):
    home, legacy, new = env
    make_overlay(legacy)
    new.mkdir()
    recorder = Recorder()
    ok, log = run_migration(home, recorder)
    (delete,) = recorder.stow_calls()
    assert (ok, delete[0][:2], delete[1], log.entries()) == (True, ["stow", "--delete"], legacy, [])
    assert legacy.is_dir() and new.is_dir()
    assert "both" in capsys.readouterr().out.lower()


def test_a_failed_unstow_of_the_leftover_only_warns(env, capsys):
    home, legacy, new = env
    make_overlay(legacy)
    new.mkdir()
    ok, _ = run_migration(home, Recorder(returncodes=[1]))
    assert ok
    assert "Could not unstow" in capsys.readouterr().out


@pytest.mark.parametrize("variable", ["DOTFILES_OVERLAY_ROOT", "DOTFILES_PRIVATE_ROOT"])
def test_an_explicit_override_variable_means_nothing_is_moved(env, monkeypatch, variable):
    home, legacy, new = env
    make_overlay(legacy)
    monkeypatch.setenv(variable, str(legacy))
    recorder = Recorder()
    ok, _ = run_migration(home, recorder)
    assert (ok, recorder.calls, legacy.is_dir(), new.exists()) == (True, [], True, False)


def test_the_legacy_variable_is_reported_as_deprecated(env, monkeypatch, capsys):
    home, legacy, _ = env
    make_overlay(legacy)
    monkeypatch.setenv("DOTFILES_PRIVATE_ROOT", str(legacy))
    run_migration(home, Recorder())
    out = capsys.readouterr().out
    assert "DOTFILES_PRIVATE_ROOT" in out and "DOTFILES_OVERLAY_ROOT" in out


def test_the_new_variable_alone_is_not_reported(env, monkeypatch, capsys):
    home, legacy, _ = env
    monkeypatch.setenv("DOTFILES_OVERLAY_ROOT", str(legacy))
    run_migration(home, Recorder())
    assert "deprecated" not in capsys.readouterr().out


def test_a_dry_run_reports_and_changes_nothing(env, capsys):
    home, legacy, new = env
    make_overlay(legacy)
    recorder = Recorder()
    ok, log = run_migration(home, recorder, dry_run=True)
    assert (ok, recorder.calls, log.entries(), legacy.is_dir(), new.exists()) == (True, [], [], True, False)
    assert ".dotfiles-overlay" in capsys.readouterr().out


def test_a_dry_run_with_both_locations_runs_no_stow(env):
    home, legacy, new = env
    make_overlay(legacy)
    new.mkdir()
    recorder = Recorder()
    run_migration(home, recorder, dry_run=True)
    assert recorder.calls == []


def test_a_linked_worktree_is_refused(env, capsys):
    home, legacy, new = env
    make_overlay(legacy)
    (legacy / ".git").write_text("gitdir: /elsewhere/.git/worktrees/x\n")
    recorder = Recorder()
    ok, _ = run_migration(home, recorder)
    assert (ok, recorder.calls, legacy.is_dir(), new.exists()) == (False, [], True, False)
    assert "worktree" in capsys.readouterr().err


def test_a_dry_run_says_a_linked_worktree_would_be_refused_and_does_not_fail(env, capsys):
    home, legacy, _ = env
    make_overlay(legacy)
    (legacy / ".git").write_text("gitdir: /elsewhere/.git/worktrees/x\n")
    ok, _ = run_migration(home, Recorder(), dry_run=True)
    assert ok
    assert "Would refuse" in capsys.readouterr().out


def test_a_second_run_does_nothing(env):
    home, legacy, _ = env
    make_overlay(legacy)
    run_migration(home, Recorder())
    recorder = Recorder()
    ok, _ = run_migration(home, recorder)
    assert (ok, recorder.calls) == (True, [])


def test_linked_worktrees_of_a_git_overlay_are_repaired_after_the_move(env):
    home, legacy, new = env
    make_overlay(legacy)
    (legacy / ".git").mkdir()
    recorder = Recorder()
    run_migration(home, recorder)
    assert recorder.git_calls() == [(["git", "-C", str(new), "worktree", "repair"], None)]
    order = [call[0][0] for call in recorder.calls]
    assert order.index("git") > order.index("stow")


def test_no_repair_is_attempted_for_an_overlay_that_is_not_a_git_checkout(env):
    home, legacy, _ = env
    make_overlay(legacy)
    recorder = Recorder()
    run_migration(home, recorder)
    assert recorder.git_calls() == []


def test_a_failed_worktree_repair_warns_and_the_move_stands(env, capsys):
    home, legacy, new = env
    make_overlay(legacy)
    (legacy / ".git").mkdir()
    ok, _ = run_migration(home, Recorder(returncodes=[0, 1]))
    assert ok and new.is_dir()
    assert f"git -C {new} worktree repair" in capsys.readouterr().out


def test_gitconfig_local_is_repointed_to_the_moved_overlay(env):
    home, legacy, new = env
    make_overlay(legacy)
    link = home / ".gitconfig.local"
    link.symlink_to(legacy / "git" / "gitconfig.local")
    run_migration(home, Recorder())
    assert os.readlink(link) == str(new / "git" / "gitconfig.local")


def test_gitconfig_local_pointing_elsewhere_is_left_alone(env, tmp_path):
    home, legacy, _ = env
    make_overlay(legacy)
    link = home / ".gitconfig.local"
    link.symlink_to(tmp_path / "other" / "gitconfig.local")
    run_migration(home, Recorder())
    assert os.readlink(link) == str(tmp_path / "other" / "gitconfig.local")


def test_a_regular_gitconfig_local_is_left_alone(env):
    home, legacy, _ = env
    make_overlay(legacy)
    (home / ".gitconfig.local").write_text("[user]\n")
    run_migration(home, Recorder())
    assert (home / ".gitconfig.local").read_text() == "[user]\n"


def rolled_back(env, recorder):
    home, legacy, new = env
    make_overlay(legacy)
    run_migration(home, Recorder())
    log = RollbackLog(home / "rollback.log")
    t = tools.Tooling(Logger(dry_run=False, verbosity=1), home, run=recorder)
    ctx = rollback.RollbackContext(t, log, home / "dotfiles", new)
    rollback._undo(ctx, log.entries()[0])
    return legacy, new


def test_rolling_back_unstows_from_the_new_path_moves_back_and_relinks(env):
    recorder = Recorder()
    legacy, new = rolled_back(env, recorder)
    delete, restow = recorder.stow_calls()
    assert (delete[0][:2], delete[1]) == (["stow", "--delete"], new)
    assert (restow[0][:2], restow[1]) == (["stow", "--restow"], legacy)
    assert (legacy / "marker").read_text() == "kept"
    assert not new.exists()


def test_rolling_back_repoints_gitconfig_local_to_the_old_path(env):
    home, legacy, new = env
    make_overlay(legacy)
    (home / ".gitconfig.local").symlink_to(legacy / "git" / "gitconfig.local")
    run_migration(home, Recorder())
    log = RollbackLog(home / "rollback.log")
    t = tools.Tooling(Logger(dry_run=False, verbosity=1), home, run=Recorder())
    rollback._undo(rollback.RollbackContext(t, log, home / "dotfiles", new), log.entries()[0])
    assert os.readlink(home / ".gitconfig.local") == str(legacy / "git" / "gitconfig.local")


def test_rolling_back_leaves_things_alone_when_the_old_place_is_taken(env, capsys):
    home, legacy, new = env
    new.mkdir()
    legacy.mkdir()
    t = tools.Tooling(Logger(dry_run=False, verbosity=1), home, run=Recorder())
    ctx = rollback.RollbackContext(t, RollbackLog(home / "rollback.log"), home / "dotfiles", new)
    rollback._undo(ctx, f"OVERLAY_MOVED:{legacy}|{new}")
    assert legacy.is_dir() and new.is_dir()
    assert f"Failed to move {new} back to {legacy}" in capsys.readouterr().out


def test_a_rollback_that_cannot_unstow_leaves_the_overlay_where_it_is(env, capsys):
    home, legacy, new = env
    make_overlay(new)
    t = tools.Tooling(Logger(dry_run=False, verbosity=1), home, run=Recorder(returncodes=[1]))
    ctx = rollback.RollbackContext(t, RollbackLog(home / "rollback.log"), home / "dotfiles", new)
    rollback._undo(ctx, f"OVERLAY_MOVED:{legacy}|{new}")
    assert new.is_dir() and not legacy.exists()
    assert f"Failed to move {new} back to {legacy}" in capsys.readouterr().out
