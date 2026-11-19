import os

import pytest
from dotfiles_setup import fsutil


def test_install_executable_copies_with_mode_0755_under_a_restrictive_umask(tmp_path):
    source = tmp_path / "source"
    source.write_bytes(b"payload")
    source.chmod(0o600)
    previous = os.umask(0o077)
    try:
        fsutil.install_executable(source, tmp_path / "target")
    finally:
        os.umask(previous)
    assert (tmp_path / "target").read_bytes() == b"payload"
    assert (tmp_path / "target").stat().st_mode & 0o777 == 0o755


def test_install_executable_removes_its_temp_file_when_the_copy_fails(tmp_path):
    target_dir = tmp_path / "dir"
    target_dir.mkdir()
    with pytest.raises(FileNotFoundError):
        fsutil.install_executable(tmp_path / "missing", target_dir / "target")
    assert list(target_dir.iterdir()) == []


def test_install_executable_removes_its_temp_file_when_the_replace_fails(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.write_bytes(b"payload")
    target_dir = tmp_path / "dir"
    target_dir.mkdir()

    def refuse(src, dst):
        raise OSError("read-only")

    monkeypatch.setattr(os, "replace", refuse)
    with pytest.raises(OSError, match="read-only"):
        fsutil.install_executable(source, target_dir / "target")
    assert list(target_dir.iterdir()) == []


def test_install_executable_leaves_the_old_target_when_the_replace_fails(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.write_bytes(b"new")
    target = tmp_path / "target"
    target.write_bytes(b"old")
    monkeypatch.setattr(os, "replace", lambda src, dst: (_ for _ in ()).throw(OSError("nope")))
    with pytest.raises(OSError):
        fsutil.install_executable(source, target)
    assert target.read_bytes() == b"old"
