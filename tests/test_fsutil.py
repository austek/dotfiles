import os
from pathlib import Path

import pytest
from dotfiles_setup import fsutil
from dotfiles_setup.result import Err, Ok


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


@pytest.fixture
def real_tool(tmp_path):
    real = tmp_path / "share" / "tool"
    real.parent.mkdir()
    real.write_bytes(b"payload")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    return real, bin_dir


def test_link_executable_creates_a_symlink_to_the_real_file(real_tool):
    real, bin_dir = real_tool
    assert fsutil.link_executable(real, "tool", bin_dir) == Ok(bin_dir / "tool")
    assert (bin_dir / "tool").is_symlink()
    assert (bin_dir / "tool").resolve() == real.resolve()


def test_link_executable_is_idempotent(real_tool):
    real, bin_dir = real_tool
    fsutil.link_executable(real, "tool", bin_dir)
    assert fsutil.link_executable(real, "tool", bin_dir) == Ok(bin_dir / "tool")
    assert [p.name for p in bin_dir.iterdir()] == ["tool"]


def test_link_executable_replaces_a_stale_symlink(real_tool, tmp_path):
    real, bin_dir = real_tool
    (bin_dir / "tool").symlink_to(tmp_path / "gone")
    assert isinstance(fsutil.link_executable(real, "tool", bin_dir), Ok)
    assert (bin_dir / "tool").resolve() == real.resolve()


def test_link_executable_refuses_a_regular_file_and_keeps_it(real_tool):
    real, bin_dir = real_tool
    (bin_dir / "tool").write_bytes(b"mine")
    result = fsutil.link_executable(real, "tool", bin_dir)
    assert isinstance(result, Err)
    assert str(bin_dir / "tool") in result.error
    assert (bin_dir / "tool").read_bytes() == b"mine"
    assert [p.name for p in bin_dir.iterdir()] == ["tool"]


def test_link_executable_refuses_a_directory_and_keeps_it(real_tool):
    real, bin_dir = real_tool
    (bin_dir / "tool").mkdir()
    (bin_dir / "tool" / "keep").write_bytes(b"x")
    assert isinstance(fsutil.link_executable(real, "tool", bin_dir), Err)
    assert (bin_dir / "tool" / "keep").read_bytes() == b"x"


def test_link_executable_resolves_a_relative_real_path_against_the_working_directory(real_tool, tmp_path, monkeypatch):
    real, bin_dir = real_tool
    monkeypatch.chdir(real.parent)
    assert isinstance(fsutil.link_executable(Path(real.name), "tool", bin_dir), Ok)
    assert os.readlink(bin_dir / "tool") == str(real)
    assert (bin_dir / "tool").resolve() == real.resolve()


def test_link_executable_counts_the_link_as_created_when_the_directory_sync_fails(real_tool, monkeypatch):
    real, bin_dir = real_tool
    monkeypatch.setattr(os, "fsync", lambda fd: (_ for _ in ()).throw(OSError("sync")))
    assert fsutil.link_executable(real, "tool", bin_dir) == Ok(bin_dir / "tool")
    assert (bin_dir / "tool").is_symlink()


def test_link_executable_removes_its_temp_link_when_the_replace_fails(real_tool, monkeypatch):
    real, bin_dir = real_tool
    monkeypatch.setattr(os, "replace", lambda src, dst: (_ for _ in ()).throw(OSError("read-only")))
    result = fsutil.link_executable(real, "tool", bin_dir)
    assert isinstance(result, Err)
    assert "read-only" in result.error
    assert list(bin_dir.iterdir()) == []
