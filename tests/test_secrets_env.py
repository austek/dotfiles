import os
import stat
import subprocess
from pathlib import Path

import pytest
from dotfiles_setup import secrets_env, tools
from dotfiles_setup.log import Logger
from dotfiles_setup.rollback import RollbackLog


def setup(tmp_path, dry_run=False):
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    t = tools.Tooling(Logger(dry_run=dry_run, verbosity=1), home)
    return t, RollbackLog(tmp_path / "log"), secrets_env.secrets_path(home)


def mode(path):
    return stat.S_IMODE(path.stat().st_mode)


def test_sec011_creates_an_empty_owner_only_file_in_an_owner_only_directory(tmp_path):
    t, log, path = setup(tmp_path)
    assert secrets_env.ensure_secrets_env(t, log)
    assert (mode(path), path.read_bytes(), mode(path.parent)) == (0o600, b"", 0o700)


def test_sec011_tracks_a_created_file_for_rollback(tmp_path):
    t, log, path = setup(tmp_path)
    secrets_env.ensure_secrets_env(t, log)
    assert f"FILE_CREATED:{path}" in log.entries()


def test_sec011_creation_is_never_wider_than_owner_only_even_under_umask_zero(tmp_path):
    t, log, path = setup(tmp_path)
    old = os.umask(0)
    try:
        secrets_env.ensure_secrets_env(t, log)
    finally:
        os.umask(old)
    assert mode(path) == 0o600


@pytest.mark.parametrize("loose", [0o644, 0o640, 0o604])
def test_sec011_tightens_a_loose_file_warns_and_keeps_its_content(tmp_path, capsys, loose):
    t, log, path = setup(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text("TOKEN=abc\n")
    path.chmod(loose)
    secrets_env.ensure_secrets_env(t, log)
    captured = capsys.readouterr()
    assert (mode(path), path.read_text()) == (0o600, "TOKEN=abc\n")
    assert f"{loose:04o}" in captured.out
    assert "abc" not in captured.out + captured.err
    assert log.entries() == []


def test_sec011_tightens_a_loose_config_directory(tmp_path):
    t, log, path = setup(tmp_path)
    path.parent.mkdir(parents=True)
    path.parent.chmod(0o755)
    secrets_env.ensure_secrets_env(t, log)
    assert mode(path.parent) == 0o700


def linked_secrets(tmp_path, target_mode=0o644):
    t, log, path = setup(tmp_path)
    path.parent.mkdir(parents=True)
    target = tmp_path / "elsewhere.env"
    target.write_text("X=1\n")
    target.chmod(target_mode)
    path.symlink_to(target)
    return t, log, path, target


def test_sec011_tightens_the_target_of_a_symlinked_file_like_the_launcher_judges_it(tmp_path):
    t, log, path, target = linked_secrets(tmp_path)
    assert secrets_env.ensure_secrets_env(t, log)
    assert (mode(target), path.is_symlink(), target.read_text()) == (0o600, True, "X=1\n")


def test_sec011_refuses_a_symlink_to_a_file_owned_by_someone_else(tmp_path, monkeypatch, capsys):
    t, log, _, target = linked_secrets(tmp_path)
    monkeypatch.setattr(secrets_env, "_usable_dir", lambda *a: True)
    monkeypatch.setattr(secrets_env.os, "geteuid", lambda: os.getuid() + 1)
    assert not secrets_env.ensure_secrets_env(t, log)
    assert mode(target) == 0o644
    assert "symlink target is owned by another user" in capsys.readouterr().out


def test_sec011_refuses_a_symlink_to_a_directory(tmp_path, capsys):
    t, log, path = setup(tmp_path)
    path.parent.mkdir(parents=True)
    path.symlink_to(tmp_path)
    assert not secrets_env.ensure_secrets_env(t, log)
    assert "symlink target is not a regular file" in capsys.readouterr().out


def test_sec011_refuses_a_dangling_symlink(tmp_path, capsys):
    t, log, path = setup(tmp_path)
    path.parent.mkdir(parents=True)
    path.symlink_to(tmp_path / "missing")
    assert not secrets_env.ensure_secrets_env(t, log)
    assert "dangling symlink" in capsys.readouterr().out


def test_sec011_refuses_a_regular_file_owned_by_someone_else(tmp_path, monkeypatch, capsys):
    t, log, path = setup(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text("X=1\n")
    monkeypatch.setattr(secrets_env, "_usable_dir", lambda *a: True)
    monkeypatch.setattr(secrets_env.os, "geteuid", lambda: os.getuid() + 1)
    assert not secrets_env.ensure_secrets_env(t, log)
    assert "file is owned by another user" in capsys.readouterr().out


def test_sec011_refuses_a_config_directory_owned_by_someone_else(tmp_path, monkeypatch, capsys):
    t, log, path = setup(tmp_path)
    path.parent.mkdir(parents=True)
    monkeypatch.setattr(secrets_env.os, "geteuid", lambda: os.getuid() + 1)
    assert not secrets_env.ensure_secrets_env(t, log)
    assert not path.exists()
    assert "not a real directory you own" in capsys.readouterr().out


def test_sec011_an_unexpected_oserror_is_logged_and_fails_the_step_keeping_earlier_records(tmp_path, monkeypatch, capsys):
    t, log, path = setup(tmp_path)
    monkeypatch.setattr(secrets_env, "_create_empty", lambda p: (_ for _ in ()).throw(PermissionError("denied")))
    assert not secrets_env.ensure_secrets_env(t, log)
    assert "secrets.env setup failed: denied" in capsys.readouterr().err
    assert log.entries()[-1] == f"DIR_CREATED:{path.parent}"


def test_sec011_directory_tightening_is_logged(tmp_path, capsys):
    t, log, path = setup(tmp_path)
    path.parent.mkdir(parents=True)
    path.parent.chmod(0o775)
    secrets_env.ensure_secrets_env(t, log)
    assert "had mode 775; restricting to 700" in capsys.readouterr().out


def test_sec011_dry_run_leaves_an_existing_loose_file_alone(tmp_path):
    t, log, path = setup(tmp_path, dry_run=True)
    path.parent.mkdir(parents=True)
    path.write_text("X=1\n")
    path.chmod(0o644)
    assert secrets_env.ensure_secrets_env(t, log)
    assert (mode(path), log.entries()) == (0o644, [])


def test_sec011_file_created_by_the_installer_is_loaded_by_the_launcher(tmp_path):
    t, log, path = setup(tmp_path)
    secrets_env.ensure_secrets_env(t, log)
    with path.open("a") as handle:
        handle.write("FOO=bar\n")
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    claude = fake_bin / "claude"
    claude.write_text('#!/bin/sh\necho "[$FOO]"\n')
    claude.chmod(0o755)
    launcher = Path(__file__).parent.parent / "bin" / "claude-foothold-launch"
    result = subprocess.run(
        [str(launcher), "n"], env={"HOME": str(t.home), "PATH": f"{fake_bin}:/usr/bin:/bin"},
        capture_output=True, text=True, check=True, cwd=tmp_path,
    )
    assert (result.stdout.strip(), result.stderr) == ("[bar]", "")


def test_sec011_never_creates_the_file_through_a_symlinked_config_dir(tmp_path, capsys):
    t, log, path = setup(tmp_path)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    elsewhere.chmod(0o755)
    path.parent.parent.mkdir(parents=True)
    path.parent.symlink_to(elsewhere)
    assert not secrets_env.ensure_secrets_env(t, log)
    assert (list(elsewhere.iterdir()), mode(elsewhere), log.entries()) == ([], 0o755, [])
    assert "not a real directory" in capsys.readouterr().out


def test_sec011_accepts_a_symlinked_dot_config_with_a_real_final_directory(tmp_path):
    t, log, _ = setup(tmp_path)
    real_config = tmp_path / "stowed-config"
    real_config.mkdir()
    (t.home / ".config").symlink_to(real_config)
    secrets_env.ensure_secrets_env(t, log)
    assert (mode(real_config / "dotfiles/secrets.env"), mode(real_config / "dotfiles")) == (0o600, 0o700)


def test_sec011_records_a_created_directory_before_its_file(tmp_path):
    t, log, path = setup(tmp_path)
    secrets_env.ensure_secrets_env(t, log)
    config = path.parent.parent
    assert log.entries() == [f"DIR_CREATED:{config}", f"DIR_CREATED:{path.parent}", f"FILE_CREATED:{path}"]


def test_sec011_does_not_record_an_existing_directory(tmp_path):
    t, log, path = setup(tmp_path)
    path.parent.mkdir(parents=True)
    secrets_env.ensure_secrets_env(t, log)
    assert log.entries() == [f"FILE_CREATED:{path}"]


def test_sec011_dry_run_writes_nothing(tmp_path, capsys):
    t, log, path = setup(tmp_path, dry_run=True)
    assert secrets_env.ensure_secrets_env(t, log)
    assert not path.parent.exists()
    assert "Would ensure" in capsys.readouterr().out
    assert log.entries() == []


def test_sec011_second_run_changes_nothing(tmp_path, capsys):
    t, log, path = setup(tmp_path)
    secrets_env.ensure_secrets_env(t, log)
    path.write_text("A=1\n")
    capsys.readouterr()
    secrets_env.ensure_secrets_env(t, log)
    captured = capsys.readouterr()
    assert (mode(path), path.read_text(), captured.out, captured.err) == (0o600, "A=1\n", "", "")
    assert len(log.entries()) == 3
