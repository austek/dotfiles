"""The generated settings.json is never absent or half-written, whatever crashes mid-swap."""
import os
import stat
from datetime import UTC, datetime

import pytest
from dotfiles_setup import claude_settings, fsutil, settings_drift
from dotfiles_setup.env import Env
from dotfiles_setup.log import Logger

MERGED = {"model": "new"}
NEW = settings_drift.render(MERGED)
OLD = '{"model": "old"}\n'
NOW = datetime(2026, 9, 21, 12, 30, 45, tzinfo=UTC)
BACKUP = "settings.json.bak-20260921123045"


class Crash(BaseException):
    pass


def _regular(target, tmp_path):
    target.write_text(OLD)
    target.chmod(0o644)


def _symlink(target, tmp_path):
    repo_copy = tmp_path / "repo-settings.json"
    repo_copy.write_text(OLD)
    target.symlink_to(repo_copy)


def _dangling(target, tmp_path):
    target.symlink_to(tmp_path / "gone.json")


def _missing(target, tmp_path):
    pass


STARTS = {
    "regular": (_regular, OLD),
    "symlink": (_symlink, OLD),
    "dangling": (_dangling, None),
    "missing": (_missing, None),
}


@pytest.fixture
def home(tmp_path):
    claude_home = tmp_path / "claude-home"
    claude_home.mkdir()
    return claude_home


@pytest.fixture
def env(tmp_path, home):
    return Env(
        clock=lambda: NOW, home=tmp_path, claude_home=home,
        state_dir=tmp_path / "state", dotfiles_dir=tmp_path,
    )


@pytest.fixture(params=STARTS)
def start(request, tmp_path, home):
    setup, old = STARTS[request.param]
    target = home / "settings.json"
    setup(target, tmp_path)
    return target, old, os.path.lexists(target)


def _write(env):
    claude_settings._write_claude_settings(Logger(dry_run=False), MERGED, env)


def _content(path):
    return path.read_text() if path.exists() else None


def _crash_on(monkeypatch, name, nth=1, exc=Crash):
    real = getattr(os, name)
    calls = []

    def wrapper(*args, **kwargs):
        calls.append(args)
        if len(calls) == nth:
            raise exc("injected")
        return real(*args, **kwargs)

    monkeypatch.setattr(os, name, wrapper)
    return calls


def _leftovers(*directories):
    return [p for d in directories if d.exists() for p in d.glob("*.tmp")]


def test_every_swap_call_sees_the_target_present_with_old_or_new_content(env, home, start, monkeypatch):
    target, old, existed = start
    seen = []

    def spy(name):
        real = getattr(os, name)

        def wrapper(*args, **kwargs):
            if str(target) in map(str, args):
                seen.append((name, os.path.lexists(target), _content(target)))
            return real(*args, **kwargs)

        monkeypatch.setattr(os, name, wrapper)

    for name in ("replace", "link", "rename"):
        spy(name)
    _write(env)
    assert any(call == "replace" for call, _, _ in seen)
    assert all(present == existed and content in (old, NEW) for _, present, content in seen)
    assert not any(call == "rename" for call, _, _ in seen)
    assert target.read_text() == NEW
    assert not target.is_symlink()


@pytest.mark.parametrize("point", ["fsync", "replace"])
def test_a_crash_before_the_swap_leaves_the_old_target_and_no_temp_file(env, home, start, monkeypatch, point):
    target, old, existed = start
    _crash_on(monkeypatch, point)
    with pytest.raises(Crash):
        _write(env)
    assert os.path.lexists(target) == existed
    assert _content(target) == old
    assert not _leftovers(home, env.state_dir)


def test_a_crash_while_writing_the_staged_file_leaves_the_old_target_and_no_temp_file(
    env, home, start, monkeypatch,
):
    target, old, existed = start
    real = os.fdopen

    class Exploding:
        def __init__(self, handle):
            self.handle = handle

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            self.handle.close()

        def write(self, text):
            raise Crash("injected")

    monkeypatch.setattr(os, "fdopen", lambda *a, **k: Exploding(real(*a, **k)))
    with pytest.raises(Crash):
        _write(env)
    assert os.path.lexists(target) == existed
    assert _content(target) == old
    assert not _leftovers(home)


def test_a_crash_while_linking_the_backup_leaves_the_old_target_and_no_backup(env, home, tmp_path, monkeypatch):
    target = home / "settings.json"
    _regular(target, tmp_path)
    _crash_on(monkeypatch, "link")
    with pytest.raises(Crash):
        _write(env)
    assert target.read_text() == OLD
    assert not list(home.glob("settings.json.bak-*"))
    assert not _leftovers(home)


def test_an_unsupported_hard_link_falls_back_to_a_copy(env, home, tmp_path, monkeypatch):
    target = home / "settings.json"
    _regular(target, tmp_path)
    _crash_on(monkeypatch, "link", exc=OSError)
    _write(env)
    assert (home / BACKUP).read_text() == OLD
    assert stat.S_IMODE((home / BACKUP).stat().st_mode) == 0o644
    assert target.read_text() == NEW


def _claim_on_first_link(monkeypatch, name, fail_with):
    real = os.link
    calls = []

    def link(source, destination, **kwargs):
        calls.append(destination)
        if len(calls) == 1:
            destination.write_text("claimed by a concurrent install")
            raise fail_with
        return real(source, destination, **kwargs)

    monkeypatch.setattr(os, name, link)


def test_a_backup_name_claimed_before_the_link_is_never_overwritten(tmp_path, monkeypatch):
    source = tmp_path / "settings.json"
    source.write_text(OLD)
    _claim_on_first_link(monkeypatch, "link", FileExistsError())
    kept = fsutil.keep_copy(source, tmp_path / "settings.bak")
    assert kept.name == "settings.bak-1"
    assert kept.read_text() == OLD
    assert (tmp_path / "settings.bak").read_text() == "claimed by a concurrent install"


def test_a_copy_fallback_never_overwrites_a_claimed_backup_name(tmp_path, monkeypatch):
    source = tmp_path / "settings.json"
    source.write_text(OLD)
    _claim_on_first_link(monkeypatch, "link", OSError())
    kept = fsutil.keep_copy(source, tmp_path / "settings.bak")
    assert kept.name == "settings.bak-1"
    assert kept.read_text() == OLD
    assert (tmp_path / "settings.bak").read_text() == "claimed by a concurrent install"


def test_a_failed_copy_fallback_leaves_no_partial_backup(tmp_path, monkeypatch):
    source = tmp_path / "settings.json"
    source.write_text(OLD)
    monkeypatch.setattr(os, "link", lambda *args, **kwargs: (_ for _ in ()).throw(OSError()))
    monkeypatch.setattr(fsutil.shutil, "copy2", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("disk full")))
    with pytest.raises(RuntimeError):
        fsutil.keep_copy(source, tmp_path / "settings.bak")
    assert not (tmp_path / "settings.bak").exists()


def test_a_failing_directory_fsync_is_swallowed(env, home, start, monkeypatch):
    target, _, _ = start
    _crash_on(monkeypatch, "fsync", nth=2, exc=OSError)
    _write(env)
    assert target.read_text() == NEW


def test_a_crash_while_recording_the_baseline_keeps_the_old_baseline_byte_for_byte(
    env, home, tmp_path, monkeypatch,
):
    _regular(home / "settings.json", tmp_path)
    settings_drift.record_baseline(env.state_dir, OLD)
    baseline = settings_drift.baseline_path(env.state_dir)
    before = baseline.read_bytes()
    _crash_on(monkeypatch, "fsync", nth=3)
    with pytest.raises(Crash):
        _write(env)
    assert baseline.read_bytes() == before
    assert (home / "settings.json").read_text() == NEW
    assert not _leftovers(home, env.state_dir)


def test_a_crash_between_settings_and_baseline_is_recovered_by_a_later_write(env, home, tmp_path, monkeypatch):
    _regular(home / "settings.json", tmp_path)
    with monkeypatch.context() as patched:
        _crash_on(patched, "fsync", nth=3)
        with pytest.raises(Crash):
            _write(env)
    assert not settings_drift.baseline_path(env.state_dir).exists()
    _write(env)
    assert settings_drift.baseline_path(env.state_dir).read_text() == NEW


def test_an_existing_mode_is_preserved_on_the_new_file_and_the_backup(env, home, tmp_path):
    target = home / "settings.json"
    _regular(target, tmp_path)
    target.chmod(0o640)
    _write(env)
    assert stat.S_IMODE(target.stat().st_mode) == 0o640
    assert stat.S_IMODE((home / BACKUP).stat().st_mode) == 0o640


@pytest.mark.parametrize("name", ["symlink", "dangling", "missing"])
def test_a_new_file_gets_mode_0600_and_no_backup(env, home, tmp_path, name):
    target = home / "settings.json"
    STARTS[name][0](target, tmp_path)
    _write(env)
    assert stat.S_IMODE(target.stat().st_mode) == 0o600
    assert not list(home.glob("settings.json.bak-*"))
    assert stat.S_IMODE(settings_drift.baseline_path(env.state_dir).stat().st_mode) == 0o600


def test_a_symlink_target_never_writes_through_to_the_repo_copy(env, home, tmp_path):
    _symlink(home / "settings.json", tmp_path)
    _write(env)
    assert (tmp_path / "repo-settings.json").read_text() == OLD


def test_the_backup_keeps_the_old_content_and_a_name_collision_adds_a_numeric_suffix(env, home, tmp_path):
    target = home / "settings.json"
    (home / BACKUP).write_text("earlier backup")
    _regular(target, tmp_path)
    _write(env)
    assert (home / BACKUP).read_text() == "earlier backup"
    assert (home / f"{BACKUP}-1").read_text() == OLD
    target.write_text(OLD)
    _write(env)
    assert (home / f"{BACKUP}-2").read_text() == OLD


def test_identical_content_is_left_untouched(env, home):
    target = home / "settings.json"
    target.write_text(NEW)
    os.utime(target, ns=(0, 0))
    _write(env)
    assert target.stat().st_mtime_ns == 0
    assert not list(home.glob("settings.json.bak-*"))


def test_a_dry_run_writes_nothing(env, home, capsys):
    claude_settings._write_claude_settings(Logger(dry_run=True), MERGED, env)
    assert not (home / "settings.json").exists()
    assert not env.state_dir.exists()
    assert f"Would generate {home / 'settings.json'}." in capsys.readouterr().out
