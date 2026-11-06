from types import SimpleNamespace

import pytest
from dotfiles_setup import flatpak
from dotfiles_setup.log import Logger
from dotfiles_setup.tooling import Tooling


class Machine:
    def __init__(self, installed=(), failing=()):
        self.commands = []
        self.installed = set(installed)
        self.failing = tuple(failing)

    def __call__(self, argv, **kwargs):
        self.commands.append(list(argv))
        if argv[:3] == ["flatpak", "info", "--user"]:
            return SimpleNamespace(returncode=0 if argv[3] in self.installed else 1, stdout="", stderr="")
        failed = any(argv[: len(p)] == list(p) for p in self.failing)
        return SimpleNamespace(returncode=1 if failed else 0, stdout="", stderr="")

    def ran(self, *prefix):
        return any(c[: len(prefix)] == list(prefix) for c in self.commands)


@pytest.fixture
def has_flatpak(monkeypatch):
    monkeypatch.setattr(flatpak.shutil, "which", lambda name: "/usr/bin/flatpak")


def tooling(tmp_path, machine, dry_run=False):
    return Tooling(Logger(dry_run=dry_run, verbosity=1), tmp_path, run=machine)


def test_only_prefixed_entries_are_app_ids():
    assert flatpak.app_ids(["vim", "flatpak:org.b.B", "flatpak:org.a.A"]) == ["org.a.A", "org.b.B"]


def test_no_flatpak_entries_means_no_calls(tmp_path):
    machine = Machine()
    flatpak.install_flatpaks(tooling(tmp_path, machine), ["vim"])
    assert machine.commands == []


def test_missing_apps_are_installed_user_level_from_flathub(tmp_path, has_flatpak):
    machine = Machine()
    flatpak.install_flatpaks(tooling(tmp_path, machine), ["flatpak:com.slack.Slack"])
    assert machine.ran("flatpak", "remote-add", "--user", "--if-not-exists", "flathub", flatpak.FLATHUB_REPO)
    assert machine.ran("flatpak", "install", "--user", "-y", "--noninteractive", "flathub", "com.slack.Slack")
    assert not machine.ran("sudo")


def test_an_installed_app_is_not_reinstalled(tmp_path, has_flatpak):
    machine = Machine(installed=["com.slack.Slack"])
    flatpak.install_flatpaks(tooling(tmp_path, machine), ["flatpak:com.slack.Slack"])
    assert not machine.ran("flatpak", "install")


def test_update_runs_only_when_upgrading(tmp_path, has_flatpak):
    plain, upgrading = Machine(), Machine()
    flatpak.install_flatpaks(tooling(tmp_path, plain), ["flatpak:com.slack.Slack"])
    flatpak.install_flatpaks(tooling(tmp_path, upgrading), ["flatpak:com.slack.Slack"], upgrade=True)
    assert not plain.ran("flatpak", "update")
    assert upgrading.ran("flatpak", "update", "--user", "-y", "--noninteractive")


def test_a_missing_flatpak_binary_skips_without_failing(tmp_path, monkeypatch):
    monkeypatch.setattr(flatpak.shutil, "which", lambda name: None)
    machine = Machine()
    flatpak.install_flatpaks(tooling(tmp_path, machine), ["flatpak:com.slack.Slack"])
    assert machine.commands == []


def test_a_failed_remote_add_skips_the_installs_without_failing(tmp_path, has_flatpak):
    machine = Machine(failing=[("flatpak", "remote-add")])
    flatpak.install_flatpaks(tooling(tmp_path, machine), ["flatpak:com.slack.Slack"])
    assert not machine.ran("flatpak", "install")


def test_one_failed_install_does_not_stop_the_next(tmp_path, has_flatpak):
    machine = Machine(failing=[("flatpak", "install", "--user", "-y", "--noninteractive", "flathub", "com.a.A")])
    flatpak.install_flatpaks(tooling(tmp_path, machine), ["flatpak:com.a.A", "flatpak:com.b.B"])
    assert machine.ran("flatpak", "install", "--user", "-y", "--noninteractive", "flathub", "com.b.B")


def test_upgrade_updates_installed_apps_even_without_flatpak_entries(tmp_path, has_flatpak):
    machine = Machine()
    flatpak.install_flatpaks(tooling(tmp_path, machine), ["vim"], upgrade=True)
    assert machine.ran("flatpak", "update", "--user", "-y", "--noninteractive")
    assert not machine.ran("flatpak", "remote-add")


def test_upgrade_without_flatpak_installed_is_not_an_error(tmp_path, monkeypatch):
    monkeypatch.setattr(flatpak.shutil, "which", lambda name: None)
    machine = Machine()
    flatpak.install_flatpaks(tooling(tmp_path, machine), ["vim"], upgrade=True)
    assert machine.commands == []


def test_a_failed_update_is_logged_and_does_not_raise(tmp_path, has_flatpak):
    machine = Machine(failing=[("flatpak", "update")])
    flatpak.install_flatpaks(tooling(tmp_path, machine), ["flatpak:com.slack.Slack"], upgrade=True)
    assert machine.ran("flatpak", "update")


def test_a_dry_run_makes_no_calls(tmp_path, has_flatpak):
    machine = Machine()
    flatpak.install_flatpaks(tooling(tmp_path, machine, dry_run=True), ["flatpak:com.slack.Slack"])
    assert machine.commands == []
