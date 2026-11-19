import os
from pathlib import Path
from types import SimpleNamespace

import pytest
from dotfiles_setup import rollback, tools
from dotfiles_setup.log import Logger


class Machine:
    def __init__(self, failing=()):
        self.commands = []
        self.failing = tuple(failing)

    def __call__(self, argv, **kwargs):
        self.commands.append((list(argv), kwargs.get("cwd")))
        failed = any(argv[: len(p)] == list(p) for p in self.failing)
        return SimpleNamespace(returncode=1 if failed else 0, stdout="", stderr="")

    def argvs(self):
        return [argv for argv, _ in self.commands]


def context(tmp_path, machine, private=None):
    t = tools.Tooling(Logger(dry_run=False, verbosity=1), tmp_path / "home", run=machine)
    log = rollback.RollbackLog(tmp_path / "rollback.log")
    return rollback.RollbackContext(t, log, tmp_path / "repo", private)


def test_tracking_appends_and_a_dry_run_records_nothing(tmp_path):
    log = rollback.RollbackLog(tmp_path / "log")
    log.track("STOW_HOME:a", dry_run=False)
    log.track("STOW_HOME:b", dry_run=False)
    log.track("STOW_HOME:c", dry_run=True)
    assert log.entries() == ["STOW_HOME:a", "STOW_HOME:b"]


def test_a_missing_log_has_no_entries(tmp_path):
    log = rollback.RollbackLog(tmp_path / "missing")
    assert log.entries() == []
    assert not log.has_entries()


def test_rule032_entries_are_undone_newest_first_and_the_log_is_removed(tmp_path):
    machine = Machine()
    ctx = context(tmp_path, machine, private=tmp_path / "private")
    for entry in ("STOW_HOME:a", "STOW_PRIVATE:b", "STOW_ROOT:c", "DOCKER_GROUP:ali", "FILE_CREATED:/etc/x.sources"):
        ctx.log.track(entry, dry_run=False)
    rollback.perform_rollback(ctx)
    assert machine.commands == [
        (["sudo", "rm", "-f", "/etc/x.sources"], None),
        (["sudo", "gpasswd", "-d", "ali", "docker"], None),
        (["sudo", "stow", "--delete", "--target=/", "c"], tmp_path / "repo"),
        (["stow", "--delete", f"--target={tmp_path / 'home'}", "b"], tmp_path / "private"),
        (["stow", "--delete", f"--target={tmp_path / 'home'}", "a"], tmp_path / "repo"),
    ]
    assert not ctx.log.path.exists()


def test_dir_created_is_removed_when_empty(tmp_path):
    ctx = context(tmp_path, Machine())
    created = tmp_path / "made"
    created.mkdir()
    ctx.log.track(f"DIR_CREATED:{created}", dry_run=False)
    rollback.perform_rollback(ctx)
    assert not created.exists()


def test_dir_created_is_never_removed_when_it_holds_files(tmp_path):
    ctx = context(tmp_path, Machine())
    created = tmp_path / "made"
    created.mkdir()
    (created / "keep").write_text("x")
    ctx.log.track(f"DIR_CREATED:{created}", dry_run=False)
    rollback.perform_rollback(ctx)
    assert (created / "keep").read_text() == "x"


def test_dir_created_on_a_missing_directory_is_silent(tmp_path, capsys):
    ctx = context(tmp_path, Machine())
    rollback._dir_created(ctx, str(tmp_path / "gone"))
    assert "WARNING" not in capsys.readouterr().out


def test_dir_created_on_a_non_empty_directory_logs_at_info_not_warning(tmp_path, capsys):
    ctx = context(tmp_path, Machine())
    (tmp_path / "full").mkdir()
    (tmp_path / "full/x").write_text("x")
    rollback._dir_created(ctx, str(tmp_path / "full"))
    assert "WARNING" not in capsys.readouterr().out


def test_dir_created_warns_on_other_errors(tmp_path, monkeypatch, capsys):
    ctx = context(tmp_path, Machine())
    monkeypatch.setattr(rollback.Path, "rmdir", lambda self: (_ for _ in ()).throw(PermissionError("denied")))
    rollback._dir_created(ctx, str(tmp_path))
    assert "WARNING" in capsys.readouterr().out


def test_rollback_removes_a_created_file_then_its_created_directory(tmp_path):
    class Removing(Machine):
        def __call__(self, argv, **kwargs):
            Path(argv[-1]).unlink(missing_ok=True)
            return super().__call__(argv, **kwargs)

    ctx = context(tmp_path, Removing())
    config = tmp_path / "cfg"
    config.mkdir()
    (config / "secrets.env").write_text("")
    ctx.log.track(f"DIR_CREATED:{config}", dry_run=False)
    ctx.log.track(f"FILE_CREATED:{config / 'secrets.env'}", dry_run=False)
    rollback.perform_rollback(ctx)
    assert not config.exists()


def installed_binary(tmp_path, content=b"bin"):
    import hashlib
    target = tmp_path / "bin" / "chip"
    target.parent.mkdir()
    target.write_bytes(content)
    return target, hashlib.sha256(b"bin").hexdigest()


def test_an_installed_user_binary_is_removed_without_sudo(tmp_path):
    machine = Machine()
    ctx = context(tmp_path, machine)
    target, digest = installed_binary(tmp_path)
    ctx.log.track(f"BIN_INSTALLED:{target}|{digest}", dry_run=False)
    rollback.perform_rollback(ctx)
    assert not target.exists()
    assert machine.commands == []


def test_a_created_user_bin_dir_is_removed_after_the_binary_installed_into_it(tmp_path):
    import hashlib
    ctx = context(tmp_path, Machine())
    created = tmp_path / "local-bin"
    created.mkdir()
    target = created / "chip"
    target.write_bytes(b"bin")
    ctx.log.track(f"DIR_CREATED:{created}", dry_run=False)
    ctx.log.track(f"BIN_INSTALLED:{target}|{hashlib.sha256(b'bin').hexdigest()}", dry_run=False)
    rollback.perform_rollback(ctx)
    assert not created.exists()


def test_a_user_binary_replaced_since_the_install_is_kept(tmp_path, capsys):
    ctx = context(tmp_path, Machine())
    target, digest = installed_binary(tmp_path, content=b"someone elses")
    ctx.log.track(f"BIN_INSTALLED:{target}|{digest}", dry_run=False)
    rollback.perform_rollback(ctx)
    assert target.read_bytes() == b"someone elses"
    assert f"Kept {target}" in capsys.readouterr().out


def replace_then_write(monkeypatch, target, content):
    import os
    real = os.replace

    def replace(src, dst):
        real(src, dst)
        target.write_bytes(content)

    monkeypatch.setattr(rollback.os, "replace", replace)


def test_a_binary_replaced_after_the_move_survives(tmp_path, monkeypatch):
    ctx = context(tmp_path, Machine())
    target, digest = installed_binary(tmp_path)
    ctx.log.track(f"BIN_INSTALLED:{target}|{digest}", dry_run=False)
    replace_then_write(monkeypatch, target, b"replacement")
    rollback.perform_rollback(ctx)
    assert target.read_bytes() == b"replacement"
    assert sorted(p.name for p in target.parent.iterdir()) == ["chip"]


def test_a_matching_binary_is_removed_and_leaves_no_temporary_file(tmp_path):
    ctx = context(tmp_path, Machine())
    target, digest = installed_binary(tmp_path)
    ctx.log.track(f"BIN_INSTALLED:{target}|{digest}", dry_run=False)
    rollback.perform_rollback(ctx)
    assert list(target.parent.iterdir()) == []


def test_a_mismatching_binary_is_put_back_without_a_temporary_file(tmp_path):
    ctx = context(tmp_path, Machine())
    target, digest = installed_binary(tmp_path, content=b"someone elses")
    ctx.log.track(f"BIN_INSTALLED:{target}|{digest}", dry_run=False)
    rollback.perform_rollback(ctx)
    assert target.read_bytes() == b"someone elses"
    assert sorted(p.name for p in target.parent.iterdir()) == ["chip"]


def test_a_mismatch_with_a_newer_target_keeps_both_and_logs_the_temporary_path(tmp_path, monkeypatch, capsys):
    ctx = context(tmp_path, Machine())
    target, digest = installed_binary(tmp_path, content=b"someone elses")
    ctx.log.track(f"BIN_INSTALLED:{target}|{digest}", dry_run=False)
    replace_then_write(monkeypatch, target, b"newer")
    rollback.perform_rollback(ctx)
    (held,) = target.parent.glob(".chip.rollback-*/chip")
    assert held.read_bytes() == b"someone elses"
    assert target.read_bytes() == b"newer"
    output = capsys.readouterr().out
    assert f"Kept {target}: it changed since the install." in output
    assert str(held) in output


def test_two_rollbacks_in_one_process_keep_both_preserved_files(tmp_path, monkeypatch):
    target, digest = installed_binary(tmp_path, content=b"first")
    for newer in (b"second", b"third"):
        ctx = context(tmp_path, Machine())
        ctx.log.discard()
        ctx.log.track(f"BIN_INSTALLED:{target}|{digest}", dry_run=False)
        replace_then_write(monkeypatch, target, newer)
        rollback.perform_rollback(ctx)
        monkeypatch.undo()
    kept = sorted(p.read_bytes() for p in target.parent.glob(".chip.rollback-*/chip"))
    assert kept == [b"first", b"second"]


@pytest.mark.skipif(os.geteuid() == 0, reason="root reads any file")
def test_an_unreadable_binary_is_put_back_and_left_alone(tmp_path, capsys):
    ctx = context(tmp_path, Machine())
    target, digest = installed_binary(tmp_path)
    target.chmod(0o111)
    ctx.log.track(f"BIN_INSTALLED:{target}|{digest}", dry_run=False)
    rollback.perform_rollback(ctx)
    assert target.stat().st_mode & 0o777 == 0o111
    assert sorted(p.name for p in target.parent.iterdir()) == ["chip"]
    assert "Kept" in capsys.readouterr().out


def test_a_binary_that_cannot_be_put_back_keeps_its_directory_and_says_where(tmp_path, monkeypatch, capsys):
    ctx = context(tmp_path, Machine())
    target, digest = installed_binary(tmp_path, content=b"someone elses")
    ctx.log.track(f"BIN_INSTALLED:{target}|{digest}", dry_run=False)
    monkeypatch.setattr(rollback.os, "link", lambda *args, **kwargs: (_ for _ in ()).throw(PermissionError("denied")))
    rollback.perform_rollback(ctx)
    (held,) = target.parent.glob(".chip.rollback-*/chip")
    assert held.read_bytes() == b"someone elses"
    assert str(held) in capsys.readouterr().out


def test_a_failed_move_whose_directory_cannot_be_removed_warns_and_does_not_escape(tmp_path, monkeypatch, capsys):
    ctx = context(tmp_path, Machine())
    target, digest = installed_binary(tmp_path)
    ctx.log.track(f"BIN_INSTALLED:{target}|{digest}", dry_run=False)
    monkeypatch.setattr(rollback.os, "replace", lambda src, dst: (_ for _ in ()).throw(PermissionError("denied")))
    monkeypatch.setattr(rollback.Path, "rmdir", lambda self: (_ for _ in ()).throw(OSError("busy")))
    rollback.perform_rollback(ctx)
    assert target.exists()
    output = capsys.readouterr().out
    assert "denied" in output
    assert "busy" in output


def swap_before_replace(monkeypatch, path, make):
    real = os.replace

    def replace(src, dst):
        if Path(src) == path:
            path.unlink()
            make(path)
        real(src, dst)

    monkeypatch.setattr(rollback.os, "replace", replace)


def test_a_link_replaced_by_a_regular_file_before_the_move_survives(tmp_path, monkeypatch):
    ctx = context(tmp_path, Machine())
    root, link = aws_install(tmp_path)
    ctx.log.track(f"LINK_INSTALLED:{root}|{link}", dry_run=False)
    swap_before_replace(monkeypatch, link, lambda path: path.write_bytes(b"mine"))
    rollback.perform_rollback(ctx)
    assert link.read_bytes() == b"mine"
    assert sorted(p.name for p in link.parent.iterdir()) == ["aws"]


def test_a_link_replaced_by_a_symlink_outside_the_root_is_restored(tmp_path, monkeypatch):
    ctx = context(tmp_path, Machine())
    root, link = aws_install(tmp_path)
    other = tmp_path / "other-aws"
    other.write_bytes(b"mine")
    ctx.log.track(f"LINK_INSTALLED:{root}|{link}", dry_run=False)
    swap_before_replace(monkeypatch, link, lambda path: path.symlink_to(other))
    rollback.perform_rollback(ctx)
    assert link.is_symlink()
    assert link.resolve() == other.resolve()
    assert sorted(p.name for p in link.parent.iterdir()) == ["aws"]


def test_a_matching_link_is_removed_and_leaves_no_temporary_directory(tmp_path):
    ctx = context(tmp_path, Machine())
    root, link = aws_install(tmp_path)
    ctx.log.track(f"LINK_INSTALLED:{root}|{link}", dry_run=False)
    rollback.perform_rollback(ctx)
    assert list(link.parent.iterdir()) == []


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores directory permissions")
@pytest.mark.parametrize("action", ["LINK_INSTALLED", "TREE_INSTALLED"])
def test_an_unreadable_link_directory_does_not_stop_the_remaining_entries(tmp_path, action):
    ctx = context(tmp_path, Machine())
    later = tmp_path / "later"
    later.mkdir()
    locked = tmp_path / "locked"
    locked.mkdir()
    ctx.log.track(f"DIR_CREATED:{later}", dry_run=False)
    ctx.log.track(f"{action}:{locked / 'root'}|{locked / 'aws'}", dry_run=False)
    locked.chmod(0)
    try:
        rollback.perform_rollback(ctx)
    finally:
        locked.chmod(0o700)
    assert not later.exists()


def test_an_already_removed_user_binary_is_not_an_error(tmp_path, capsys):
    ctx = context(tmp_path, Machine())
    ctx.log.track(f"BIN_INSTALLED:{tmp_path / 'gone'}|abc", dry_run=False)
    rollback.perform_rollback(ctx)
    assert "Unknown rollback action" not in capsys.readouterr().err


def aws_install(tmp_path):
    root, link = tmp_path / "aws-cli", tmp_path / "bin" / "aws"
    real = root / "v2" / "2.39.6" / "bin" / "aws"
    real.parent.mkdir(parents=True)
    real.write_bytes(b"aws")
    link.parent.mkdir()
    link.symlink_to(real)
    return root, link


def test_a_fresh_awscli_tree_and_its_link_are_removed(tmp_path):
    machine = Machine()
    ctx = context(tmp_path, machine)
    root, link = aws_install(tmp_path)
    ctx.log.track(f"TREE_INSTALLED:{root}|{link}", dry_run=False)
    rollback.perform_rollback(ctx)
    assert not root.exists()
    assert not link.is_symlink()
    assert machine.commands == []


def test_the_aws_completer_link_is_removed_with_aws_and_the_tree(tmp_path):
    ctx = context(tmp_path, Machine())
    root, link = aws_install(tmp_path)
    completer = link.with_name("aws_completer")
    completer.symlink_to(root / "v2" / "2.39.6" / "bin" / "aws")
    ctx.log.track(f"TREE_INSTALLED:{root}|{link}", dry_run=False)
    ctx.log.track(f"LINK_INSTALLED:{root}|{completer}", dry_run=False)
    rollback.perform_rollback(ctx)
    assert not completer.is_symlink()
    assert not link.is_symlink()
    assert not root.exists()


def test_a_retargeted_aws_completer_is_kept_and_does_not_stop_the_rest(tmp_path):
    ctx = context(tmp_path, Machine())
    root, link = aws_install(tmp_path)
    completer = link.with_name("aws_completer")
    other = tmp_path / "mine"
    other.write_bytes(b"x")
    completer.symlink_to(other)
    ctx.log.track(f"TREE_INSTALLED:{root}|{link}", dry_run=False)
    ctx.log.track(f"LINK_INSTALLED:{root}|{completer}", dry_run=False)
    rollback.perform_rollback(ctx)
    assert completer.resolve() == other.resolve()
    assert not link.is_symlink()
    assert not root.exists()


def test_a_retargeted_link_keeps_both_the_link_and_the_tree(tmp_path, capsys):
    ctx = context(tmp_path, Machine())
    root, link = aws_install(tmp_path)
    other = tmp_path / "other-aws"
    other.write_bytes(b"mine")
    link.unlink()
    link.symlink_to(other)
    ctx.log.track(f"TREE_INSTALLED:{root}|{link}", dry_run=False)
    rollback.perform_rollback(ctx)
    assert link.resolve() == other.resolve()
    assert (root / "v2" / "2.39.6" / "bin" / "aws").is_file()
    assert f"Kept {link}" in capsys.readouterr().out


def test_a_regular_file_where_the_link_was_keeps_both(tmp_path):
    ctx = context(tmp_path, Machine())
    root, link = aws_install(tmp_path)
    link.unlink()
    link.write_bytes(b"mine")
    ctx.log.track(f"TREE_INSTALLED:{root}|{link}", dry_run=False)
    rollback.perform_rollback(ctx)
    assert link.read_bytes() == b"mine"
    assert root.is_dir()


def test_a_tree_whose_link_is_already_gone_is_still_removed(tmp_path):
    ctx = context(tmp_path, Machine())
    root, link = aws_install(tmp_path)
    link.unlink()
    ctx.log.track(f"TREE_INSTALLED:{root}|{link}", dry_run=False)
    rollback.perform_rollback(ctx)
    assert not root.exists()


def test_a_link_only_entry_leaves_the_tree(tmp_path):
    ctx = context(tmp_path, Machine())
    root, link = aws_install(tmp_path)
    ctx.log.track(f"LINK_INSTALLED:{root}|{link}", dry_run=False)
    rollback.perform_rollback(ctx)
    assert not link.is_symlink()
    assert root.is_dir()


def test_a_tree_that_was_replaced_by_a_symlink_is_not_followed(tmp_path):
    ctx = context(tmp_path, Machine())
    root, link = aws_install(tmp_path)
    precious = tmp_path / "precious"
    precious.mkdir()
    (precious / "keep").write_bytes(b"x")
    link.unlink()
    import shutil
    shutil.rmtree(root)
    root.symlink_to(precious)
    ctx.log.track(f"TREE_INSTALLED:{root}|{link}", dry_run=False)
    rollback.perform_rollback(ctx)
    assert (precious / "keep").is_file()


def test_an_already_removed_awscli_tree_is_not_an_error(tmp_path, capsys):
    ctx = context(tmp_path, Machine())
    ctx.log.track(f"TREE_INSTALLED:{tmp_path / 'gone'}|{tmp_path / 'gone-link'}", dry_run=False)
    rollback.perform_rollback(ctx)
    assert "Unknown rollback action" not in capsys.readouterr().err


def test_an_unstowed_private_package_is_restowed(tmp_path):
    machine = Machine()
    ctx = context(tmp_path, machine, private=tmp_path / "private")
    ctx.log.track("UNSTOW_PRIVATE:claude-collibra", dry_run=False)
    rollback.perform_rollback(ctx)
    assert machine.commands == [
        (["stow", "--restow", "--no-folding", f"--target={tmp_path / 'home'}", "claude-collibra"], tmp_path / "private"),
    ]


def test_a_backed_up_file_is_restored_to_its_original_name(tmp_path):
    machine = Machine()
    ctx = context(tmp_path, machine)
    backup = tmp_path / "hosts.backup-20260101"
    backup.write_text("old")
    ctx.log.track(f"FILE_BACKUP:{backup}", dry_run=False)
    rollback.perform_rollback(ctx)
    assert machine.argvs() == [["sudo", "mv", str(backup), str(tmp_path / "hosts")]]


def test_a_backup_kept_elsewhere_is_restored_to_the_recorded_original(tmp_path):
    machine = Machine()
    ctx = context(tmp_path, machine)
    backup = tmp_path / "backups" / "docker.sources.backup-1"
    backup.parent.mkdir()
    backup.write_text("old")
    original = tmp_path / "etc" / "docker.sources"
    ctx.log.track(f"FILE_BACKUP:{backup}|{original}", dry_run=False)
    rollback.perform_rollback(ctx)
    assert machine.argvs() == [["sudo", "mv", str(backup), str(original)]]


def test_a_moved_relative_symlink_that_now_dangles_is_still_restored(tmp_path):
    machine = Machine()
    ctx = context(tmp_path, machine)
    backup = tmp_path / "backups" / "claude-desktop.backup-1"
    backup.parent.mkdir()
    backup.symlink_to("../../home/user/.dotfiles/apt/etc/default/claude-desktop")
    assert not backup.exists()
    original = tmp_path / "etc" / "claude-desktop"
    ctx.log.track(f"FILE_BACKUP:{backup}|{original}", dry_run=False)
    rollback.perform_rollback(ctx)
    assert machine.argvs() == [["sudo", "mv", str(backup), str(original)]]


def test_a_missing_backup_file_is_skipped(tmp_path):
    machine = Machine()
    ctx = context(tmp_path, machine)
    ctx.log.track(f"FILE_BACKUP:{tmp_path}/gone.backup-1", dry_run=False)
    rollback.perform_rollback(ctx)
    assert machine.commands == []


def test_a_failing_undo_does_not_stop_the_rest(tmp_path):
    machine = Machine(failing=[("stow",)])
    ctx = context(tmp_path, machine)
    ctx.log.track("DOCKER_GROUP:ali", dry_run=False)
    ctx.log.track("STOW_HOME:a", dry_run=False)
    rollback.perform_rollback(ctx)
    assert len(machine.commands) == 2
    assert not ctx.log.path.exists()


def test_an_unknown_action_is_reported_and_skipped(tmp_path):
    machine = Machine()
    ctx = context(tmp_path, machine)
    ctx.log.track("MYSTERY:x", dry_run=False)
    rollback.perform_rollback(ctx)
    assert machine.commands == []


def test_rolling_back_an_empty_log_does_nothing(tmp_path):
    machine = Machine()
    rollback.perform_rollback(context(tmp_path, machine))
    assert machine.commands == []


def test_a_confirmed_prompt_rolls_back(tmp_path):
    machine = Machine()
    ctx = context(tmp_path, machine)
    ctx.log.track("DOCKER_GROUP:ali", dry_run=False)
    rollback.offer_rollback(ctx, interactive=True, ask=lambda prompt: "Y")
    assert len(machine.commands) == 1


def test_a_declined_prompt_keeps_the_log(tmp_path):
    machine = Machine()
    ctx = context(tmp_path, machine)
    ctx.log.track("DOCKER_GROUP:ali", dry_run=False)
    rollback.offer_rollback(ctx, interactive=True, ask=lambda prompt: "")
    assert machine.commands == []
    assert ctx.log.path.exists()


def test_a_non_interactive_run_never_prompts(tmp_path):
    ctx = context(tmp_path, Machine())
    ctx.log.track("DOCKER_GROUP:ali", dry_run=False)

    def refuse(prompt):
        raise AssertionError(prompt)

    rollback.offer_rollback(ctx, interactive=False, ask=refuse)
    assert ctx.log.path.exists()


def test_nothing_is_offered_without_a_log(tmp_path):
    def refuse(prompt):
        raise AssertionError(prompt)

    rollback.offer_rollback(context(tmp_path, Machine()), interactive=True, ask=refuse)


def test_rule032_undo_reinstalls_removed_packages(tmp_path):
    machine = Machine()
    ctx = context(tmp_path, machine)
    ctx.log.track("APT_REMOVED:vim", dry_run=False)
    ctx.log.track("FLATPAK_REMOVED:com.slack.Slack", dry_run=False)
    rollback.perform_rollback(ctx)
    assert machine.argvs() == [
        ["flatpak", "install", "--user", "-y", "--noninteractive", "flathub", "com.slack.Slack"],
        ["sudo", "apt-get", "install", "-y", "vim"],
    ]


def test_rule032_undo_of_a_removed_deb_warns_and_runs_nothing(tmp_path, capsys):
    machine = Machine()
    ctx = context(tmp_path, machine)
    ctx.log.track("DEB_REMOVED:k9s", dry_run=False)
    rollback.perform_rollback(ctx)
    assert machine.argvs() == []
    assert "reinstall k9s manually" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("action", "failing"),
    [("APT_REMOVED", ("sudo", "apt-get", "install")), ("FLATPAK_REMOVED", ("flatpak", "install"))],
)
def test_a_failed_reinstall_only_warns(tmp_path, capsys, action, failing):
    machine = Machine(failing=[failing])
    ctx = context(tmp_path, machine)
    ctx.log.track(f"{action}:vim", dry_run=False)
    rollback.perform_rollback(ctx)
    assert "Failed to reinstall vim" in capsys.readouterr().out
    assert not ctx.log.path.exists()


def test_the_default_log_lives_in_home(tmp_path):
    assert rollback.RollbackLog.for_home(Path(tmp_path)).path == tmp_path / ".dotfiles-setup-rollback.log"
