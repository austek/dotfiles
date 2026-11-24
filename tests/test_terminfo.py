import hashlib
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from dotfiles_setup import rollback, terminfo, tools
from dotfiles_setup.log import Logger

SOURCE = Path(__file__).resolve().parent.parent / "terminfo" / "xterm-ghostty.terminfo"


class Tracker:
    def __init__(self):
        self.entries = []

    def track(self, entry, *, dry_run):
        self.entries.append(entry)


class Machine:
    def __init__(self, home, *, present=False, tic_status=0):
        self.home = home
        self.present = present
        self.tic_status = tic_status
        self.calls = []

    def __call__(self, argv, **kwargs):
        self.calls.append(list(argv))
        if argv[0] == "infocmp":
            return SimpleNamespace(returncode=0 if self.present else 1, stdout="", stderr="")
        if self.tic_status == 0:
            installed = self.home / ".terminfo/x/xterm-ghostty"
            installed.parent.mkdir(parents=True, exist_ok=True)
            installed.write_bytes(b"compiled")
        return SimpleNamespace(returncode=self.tic_status, stdout="", stderr="")

    def tic_calls(self):
        return [c for c in self.calls if c[0] == "tic"]


def tooling(home, machine, dry_run=False):
    return tools.Tooling(Logger(dry_run=dry_run, verbosity=1), home, run=machine)


def test_a_missing_entry_is_pending_when_tic_exists_and_nothing_runs(tmp_path, monkeypatch):
    monkeypatch.setattr("dotfiles_setup.terminfo.shutil.which", lambda name: "/usr/bin/tic")
    machine = Machine(tmp_path)
    assert terminfo.pending(tooling(tmp_path, machine)) == [f"install xterm-ghostty terminfo into {tmp_path / '.terminfo'}"]
    assert machine.tic_calls() == []


def test_a_resolving_entry_is_not_pending(tmp_path, monkeypatch):
    monkeypatch.setattr("dotfiles_setup.terminfo.shutil.which", lambda name: "/usr/bin/tic")
    assert terminfo.pending(tooling(tmp_path, Machine(tmp_path, present=True))) == []


def test_nothing_is_pending_without_tic_because_the_step_could_not_act(tmp_path, monkeypatch):
    monkeypatch.setattr("dotfiles_setup.terminfo.shutil.which", lambda name: None)
    assert terminfo.pending(tooling(tmp_path, Machine(tmp_path))) == []


def test_an_entry_that_already_resolves_is_left_alone(tmp_path):
    machine, tracker = Machine(tmp_path, present=True), Tracker()
    assert terminfo.install_ghostty_terminfo(tooling(tmp_path, machine), SOURCE, tracker) is None
    assert machine.tic_calls() == []
    assert tracker.entries == []


def test_a_missing_entry_is_compiled_into_the_user_terminfo_dir_and_recorded(tmp_path):
    machine, tracker = Machine(tmp_path), Tracker()
    assert terminfo.install_ghostty_terminfo(tooling(tmp_path, machine), SOURCE, tracker) is None
    assert machine.tic_calls() == [["tic", "-x", "-o", str(tmp_path / ".terminfo"), str(SOURCE)]]
    installed = tmp_path / ".terminfo/x/xterm-ghostty"
    digest = hashlib.sha256(b"compiled").hexdigest()
    assert tracker.entries == [
        f"DIR_CREATED:{tmp_path / '.terminfo'}",
        f"DIR_CREATED:{tmp_path / '.terminfo/x'}",
        f"TERMINFO_INSTALLED:{installed}|{digest}",
    ]


def test_an_existing_terminfo_dir_is_not_recorded_as_created(tmp_path):
    (tmp_path / ".terminfo/x").mkdir(parents=True)
    tracker = Tracker()
    terminfo.install_ghostty_terminfo(tooling(tmp_path, Machine(tmp_path)), SOURCE, tracker)
    assert [e.split(":")[0] for e in tracker.entries] == ["TERMINFO_INSTALLED"]


def test_a_missing_tic_warns_and_does_not_fail(tmp_path, capsys):
    machine, tracker = Machine(tmp_path, tic_status=127), Tracker()
    assert terminfo.install_ghostty_terminfo(tooling(tmp_path, machine), SOURCE, tracker) is None
    assert tracker.entries == []
    assert "tic" in capsys.readouterr().out


def test_a_failing_tic_warns_and_does_not_fail(tmp_path, capsys):
    machine, tracker = Machine(tmp_path, tic_status=1), Tracker()
    assert terminfo.install_ghostty_terminfo(tooling(tmp_path, machine), SOURCE, tracker) is None
    assert tracker.entries == []
    assert "xterm-ghostty" in capsys.readouterr().out


def test_a_dry_run_compiles_nothing(tmp_path, capsys):
    machine, tracker = Machine(tmp_path), Tracker()
    assert terminfo.install_ghostty_terminfo(tooling(tmp_path, machine, dry_run=True), SOURCE, tracker) is None
    assert machine.tic_calls() == []
    assert tracker.entries == []
    assert "Would install" in capsys.readouterr().out


def rollback_context(tmp_path):
    t = tooling(tmp_path / "home", Machine(tmp_path))
    return rollback.RollbackContext(t, rollback.RollbackLog(tmp_path / "rollback.log"), tmp_path / "repo", None)


def recorded_install(tmp_path):
    installed = tmp_path / "home/.terminfo/x/xterm-ghostty"
    installed.parent.mkdir(parents=True)
    installed.write_bytes(b"compiled")
    return installed, hashlib.sha256(b"compiled").hexdigest()


def test_rollback_removes_the_recorded_file_and_the_dirs_made_for_it(tmp_path):
    ctx = rollback_context(tmp_path)
    installed, digest = recorded_install(tmp_path)
    for entry in (f"DIR_CREATED:{installed.parent.parent}", f"DIR_CREATED:{installed.parent}",
                  f"TERMINFO_INSTALLED:{installed}|{digest}"):
        ctx.log.track(entry, dry_run=False)
    rollback.perform_rollback(ctx)
    assert not installed.parent.parent.exists()


def test_rollback_keeps_a_file_that_changed_since_the_install(tmp_path, capsys):
    ctx = rollback_context(tmp_path)
    installed, digest = recorded_install(tmp_path)
    installed.write_bytes(b"edited by hand")
    ctx.log.track(f"TERMINFO_INSTALLED:{installed}|{digest}", dry_run=False)
    rollback.perform_rollback(ctx)
    assert installed.read_bytes() == b"edited by hand"
    assert f"Kept {installed}" in capsys.readouterr().out


@pytest.mark.skipif(shutil.which("tic") is None or shutil.which("infocmp") is None, reason="ncurses tools missing")
def test_the_shipped_source_creates_one_entry_and_no_alias_for_rollback_to_miss(tmp_path):
    subprocess.run(["tic", "-x", "-o", str(tmp_path), str(SOURCE)], check=True)
    created = [p for p in tmp_path.rglob("*") if not p.is_dir()]
    assert [p.name for p in created] == ["xterm-ghostty"]
    assert not any(p.is_symlink() for p in created)


@pytest.mark.skipif(shutil.which("tic") is None or shutil.which("infocmp") is None, reason="ncurses tools missing")
def test_the_shipped_source_compiles_and_resolves(tmp_path):
    subprocess.run(["tic", "-x", "-o", str(tmp_path), str(SOURCE)], check=True)
    found = subprocess.run(["infocmp", "-x", "-A", str(tmp_path), "xterm-ghostty"], check=False, capture_output=True, text=True)
    assert found.returncode == 0
    assert "xterm-ghostty" in found.stdout
