from types import SimpleNamespace

import pytest
from dotfiles_setup import desktop_defaults as dd
from dotfiles_setup import tools
from dotfiles_setup.log import Logger


class Machine:
    def __init__(self, failing=()):
        self.commands = []
        self.failing = tuple(failing)

    def __call__(self, argv, **kwargs):
        self.commands.append(list(argv))
        failed = any(argv[: len(p)] == list(p) for p in self.failing)
        return SimpleNamespace(returncode=1 if failed else 0, stdout="", stderr="")

    def ran(self, *prefix):
        return any(c[: len(prefix)] == list(prefix) for c in self.commands)


@pytest.fixture
def on_path(monkeypatch):
    present = {}
    monkeypatch.setattr("shutil.which", lambda name, path=None: present.get(name))
    return present


@pytest.fixture(autouse=True)
def config_home(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("SHELL", "/bin/bash")


def make(tmp_path, machine, dry_run=False):
    return tools.Tooling(Logger(dry_run=dry_run, verbosity=1), tmp_path, run=machine)


def test_the_shell_is_switched_with_usermod(tmp_path, on_path, monkeypatch):
    on_path["zsh"] = "/usr/bin/zsh"
    monkeypatch.setattr("getpass.getuser", lambda: "ali")
    machine = Machine()
    dd.change_shell(make(tmp_path, machine))
    assert machine.commands == [["sudo", "usermod", "-s", "/usr/bin/zsh", "ali"]]


def test_a_shell_that_is_already_zsh_is_left_alone(tmp_path, on_path, monkeypatch):
    on_path["zsh"] = "/usr/bin/zsh"
    monkeypatch.setenv("SHELL", "/usr/bin/zsh")
    machine = Machine()
    dd.change_shell(make(tmp_path, machine))
    assert machine.commands == []


def test_the_shell_change_is_a_dry_run_notice_only(tmp_path, on_path):
    on_path["zsh"] = "/usr/bin/zsh"
    machine = Machine()
    dd.change_shell(make(tmp_path, machine, dry_run=True))
    assert machine.commands == []


def test_ghostty_not_installed_skips_everything(tmp_path, on_path):
    machine = Machine()
    dd.set_default_terminal(make(tmp_path, machine))
    assert machine.commands == []


def test_a_dry_run_registers_nothing(tmp_path, on_path):
    on_path["ghostty"] = "/usr/bin/ghostty"
    machine = Machine()
    dd.set_default_terminal(make(tmp_path, machine, dry_run=True))
    assert machine.commands == []
    assert not (tmp_path / "config").exists()


def test_ghostty_becomes_the_alternative_the_xdg_default_and_the_gnome_default(tmp_path, on_path):
    on_path.update({"ghostty": "/usr/bin/ghostty", "gsettings": "/usr/bin/gsettings"})
    machine = Machine()
    dd.set_default_terminal(make(tmp_path, machine))
    assert machine.ran("sudo", "update-alternatives", "--install", "/usr/bin/x-terminal-emulator", "x-terminal-emulator", "/usr/bin/ghostty", "50")
    assert machine.ran("sudo", "update-alternatives", "--set", "x-terminal-emulator", "/usr/bin/ghostty")
    assert machine.ran("gsettings", "set", dd.TERMINAL_SCHEMA, "exec", "/usr/bin/ghostty")
    assert machine.ran("gsettings", "set", dd.TERMINAL_SCHEMA, "exec-arg", "-e")
    assert (tmp_path / "config/xdg-terminals.list").read_text() == f"{dd.GHOSTTY_ENTRY_ID}\n"


def test_existing_terminal_entries_follow_ghostty_without_duplicates(tmp_path, on_path):
    on_path["ghostty"] = "/usr/bin/ghostty"
    config = tmp_path / "config"
    config.mkdir()
    (config / "xdg-terminals.list").write_text(f"foot.desktop\n{dd.GHOSTTY_ENTRY_ID}\nkitty.desktop\n")
    (config / "ubuntu-xdg-terminals.list").write_text("gnome-terminal.desktop\n")
    dd.set_default_terminal(make(tmp_path, Machine()))
    assert (config / "xdg-terminals.list").read_text() == f"{dd.GHOSTTY_ENTRY_ID}\nfoot.desktop\nkitty.desktop\n"
    assert (config / "ubuntu-xdg-terminals.list").read_text() == f"{dd.GHOSTTY_ENTRY_ID}\ngnome-terminal.desktop\n"


def test_gsettings_is_skipped_when_unavailable(tmp_path, on_path):
    on_path["ghostty"] = "/usr/bin/ghostty"
    machine = Machine()
    dd.set_default_terminal(make(tmp_path, machine))
    assert not machine.ran("gsettings")


def test_a_failed_alternative_install_does_not_stop_the_xdg_update(tmp_path, on_path):
    on_path["ghostty"] = "/usr/bin/ghostty"
    machine = Machine(failing=[("sudo", "update-alternatives", "--install")])
    dd.set_default_terminal(make(tmp_path, machine))
    assert not machine.ran("sudo", "update-alternatives", "--set")
    assert (tmp_path / "config/xdg-terminals.list").is_file()
