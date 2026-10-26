from types import SimpleNamespace

import pytest
from dotfiles_setup import system_steps as ss
from dotfiles_setup import tools
from dotfiles_setup.log import Logger
from dotfiles_setup.rollback import RollbackLog


class Machine:
    def __init__(self, failing=(), outputs=None):
        self.commands = []
        self.failing = tuple(failing)
        self.outputs = outputs or {}

    def __call__(self, argv, **kwargs):
        self.commands.append(list(argv))
        failed = any(argv[: len(p)] == list(p) for p in self.failing)
        out = next((v for p, v in self.outputs.items() if argv[: len(p)] == list(p)), "")
        return SimpleNamespace(returncode=1 if failed else 0, stdout=out, stderr="")

    def ran(self, *prefix):
        return any(c[: len(prefix)] == list(prefix) for c in self.commands)


@pytest.fixture
def on_path(monkeypatch):
    present = set()
    monkeypatch.setattr("shutil.which", lambda name, path=None: f"/usr/bin/{name}" if name in present else None)
    return present


def make(tmp_path, machine, packages=(), dry_run=False):
    t = tools.Tooling(Logger(dry_run=dry_run, verbosity=1), tmp_path, run=machine)
    return ss.SystemContext(t, tmp_path / "repo", frozenset(packages), RollbackLog(tmp_path / "rollback.log"))


def test_core_dependencies_are_installed_with_apt(tmp_path):
    machine = Machine()
    assert ss.install_core_deps(make(tmp_path, machine))
    assert machine.commands == [["sudo", "apt-get", "install", "-y", *ss.CORE_PACKAGES]]


def test_a_failed_core_install_stops_the_run(tmp_path):
    assert not ss.install_core_deps(make(tmp_path, Machine(failing=[("sudo",)])))


def test_core_dependencies_are_not_installed_in_a_dry_run(tmp_path):
    machine = Machine()
    assert ss.install_core_deps(make(tmp_path, machine, dry_run=True))
    assert machine.commands == []


def test_snapd_is_blocked_with_a_root_stow_and_the_stow_is_tracked(tmp_path, on_path):
    machine = Machine()
    ctx = make(tmp_path, machine)
    assert ss.disable_snapd(ctx)
    assert machine.commands == [
        ["sudo", "stow", f"--dir={tmp_path / 'repo'}", "--restow", "--target=/", "--verbose=1", "system"],
    ]
    assert ctx.changes.entries() == ["STOW_ROOT:system"]


def test_a_failed_system_stow_is_not_tracked_but_does_not_stop_the_step(tmp_path, on_path):
    ctx = make(tmp_path, Machine(failing=[("sudo", "stow")]))
    assert ss.disable_snapd(ctx)
    assert ctx.changes.entries() == []


def test_snap_packages_and_snapd_are_removed(tmp_path, on_path):
    on_path.add("snap")
    listing = "Name Version Rev\nfirefox 1 2\ncore22 1 2\n"
    machine = Machine(outputs={("snap", "list"): listing})
    assert ss.disable_snapd(make(tmp_path, machine))
    assert machine.ran("sudo", "snap", "remove", "--purge", "firefox")
    assert machine.ran("sudo", "snap", "remove", "--purge", "core22")
    assert machine.ran("sudo", "apt-get", "remove", "-y", "--purge", "snapd")
    assert machine.ran("sudo", "apt-get", "-y", "autoremove", "--purge")


def test_a_snap_that_will_not_remove_does_not_stop_the_rest(tmp_path, on_path):
    on_path.add("snap")
    machine = Machine(failing=[("sudo", "snap", "remove")], outputs={("snap", "list"): "h\nfirefox 1 2\nlxd 1 2\n"})
    assert ss.disable_snapd(make(tmp_path, machine))
    assert machine.ran("sudo", "snap", "remove", "--purge", "lxd")
    assert machine.ran("sudo", "apt-get", "remove")


def test_a_failed_autoremove_stops_the_run(tmp_path, on_path):
    on_path.add("snap")
    machine = Machine(failing=[("sudo", "apt-get", "-y", "autoremove")])
    assert not ss.disable_snapd(make(tmp_path, machine))


def test_snapd_removal_is_a_dry_run_notice_only(tmp_path, on_path):
    machine = Machine()
    assert ss.disable_snapd(make(tmp_path, machine, dry_run=True))
    assert machine.commands == []


def test_snap_is_stripped_from_the_system_path_after_a_tracked_backup(tmp_path):
    env = tmp_path / "environment"
    env.write_text('PATH="/usr/bin:/snap/bin"\n')
    machine = Machine()
    ctx = make(tmp_path, machine)
    assert ss.strip_snap_from_system_path(ctx, env)
    assert machine.commands[0][:4] == ["sudo", "cp", "-a", str(env)]
    assert machine.commands[1] == ["sudo", "sed", "-i", "-e", "s#:/snap/bin##g", "-e", "s#/snap/bin:##g", str(env)]
    assert ctx.changes.entries()[0].startswith(f"FILE_BACKUP:{env}.backup-")


def test_a_path_without_snap_is_left_alone(tmp_path):
    env = tmp_path / "environment"
    env.write_text('PATH="/usr/bin"\n')
    machine = Machine()
    assert ss.strip_snap_from_system_path(make(tmp_path, machine), env)
    assert machine.commands == []


def test_a_missing_environment_file_is_skipped(tmp_path):
    machine = Machine()
    assert ss.strip_snap_from_system_path(make(tmp_path, machine), tmp_path / "missing")
    assert machine.commands == []


def test_the_path_edit_is_a_dry_run_notice_only(tmp_path):
    env = tmp_path / "environment"
    env.write_text("/snap/bin")
    machine = Machine()
    assert ss.strip_snap_from_system_path(make(tmp_path, machine, dry_run=True), env)
    assert machine.commands == []


def test_gpaste_is_skipped_unless_selected(tmp_path, on_path):
    on_path.add("gnome-extensions")
    machine = Machine()
    assert ss.enable_gpaste_extension(make(tmp_path, machine)) is None
    assert machine.commands == []


def test_gpaste_is_enabled_when_selected(tmp_path, on_path):
    on_path.add("gnome-extensions")
    machine = Machine()
    ss.enable_gpaste_extension(make(tmp_path, machine, packages=["gnome-shell-extension-gpaste"]))
    assert machine.ran("gnome-extensions", "enable", ss.GPASTE_ID)


def test_gpaste_without_gnome_extensions_is_skipped(tmp_path, on_path):
    machine = Machine()
    ss.enable_gpaste_extension(make(tmp_path, machine, packages=["gnome-shell-extension-gpaste"]))
    assert machine.commands == []


def test_a_failed_gpaste_enable_only_warns(tmp_path, on_path):
    on_path.add("gnome-extensions")
    machine = Machine(failing=[("gnome-extensions",)])
    assert ss.enable_gpaste_extension(make(tmp_path, machine, packages=["gnome-shell-extension-gpaste"])) is None


def test_the_docker_group_is_ignored_without_docker(tmp_path):
    machine = Machine()
    assert ss.configure_docker_group(make(tmp_path, machine), "ali")
    assert machine.commands == []


def test_the_docker_group_is_created_and_the_user_added_and_tracked(tmp_path):
    machine = Machine(failing=[("getent",)], outputs={("groups",): "ali : ali sudo"})
    ctx = make(tmp_path, machine, packages=["docker-ce"])
    assert ss.configure_docker_group(ctx, "ali")
    assert machine.ran("sudo", "groupadd", "docker")
    assert machine.ran("sudo", "usermod", "-aG", "docker", "ali")
    assert ctx.changes.entries() == ["DOCKER_GROUP:ali"]


def test_a_user_already_in_the_docker_group_is_left_alone(tmp_path):
    machine = Machine(outputs={("groups",): "ali : ali docker"})
    ctx = make(tmp_path, machine, packages=["docker-ce"])
    assert ss.configure_docker_group(ctx, "ali")
    assert not machine.ran("sudo")
    assert ctx.changes.entries() == []


def test_a_group_named_like_docker_is_not_mistaken_for_it(tmp_path):
    machine = Machine(outputs={("groups",): "ali : ali docker-rootless"})
    assert ss.configure_docker_group(make(tmp_path, machine, packages=["docker-ce"]), "ali")
    assert machine.ran("sudo", "usermod", "-aG", "docker", "ali")


def test_the_docker_group_is_a_dry_run_notice_only(tmp_path):
    machine = Machine(failing=[("getent",)], outputs={("groups",): "ali : ali"})
    assert ss.configure_docker_group(make(tmp_path, machine, packages=["docker-ce"], dry_run=True), "ali")
    assert not machine.ran("sudo")


def test_sudo_credentials_are_checked_and_the_refresh_loop_stops(tmp_path):
    machine = Machine()
    session = ss.SudoSession(make(tmp_path, machine))
    assert session.start()
    session.stop()
    assert machine.commands == [["sudo", "-v"]]


def test_a_failed_sudo_prompt_fails_the_session(tmp_path):
    assert not ss.SudoSession(make(tmp_path, Machine(failing=[("sudo", "-v")]))).start()


def test_sudo_is_not_prompted_in_a_dry_run(tmp_path):
    machine = Machine()
    assert ss.SudoSession(make(tmp_path, machine, dry_run=True)).start()
    assert machine.commands == []


def test_the_refresh_loop_renews_credentials_until_stopped(tmp_path, monkeypatch):
    monkeypatch.setattr(ss, "SUDO_REFRESH_SECONDS", 0.01)
    machine = Machine()
    session = ss.SudoSession(make(tmp_path, machine))
    session.start()
    for _ in range(200):
        if machine.ran("sudo", "-n", "true"):
            break
        session._thread.join(0.01)
    session.stop()
    session._thread.join(1)
    assert machine.ran("sudo", "-n", "true")
    assert not session._thread.is_alive()
