import os
from types import SimpleNamespace

import pytest
from dotfiles_setup import desktop_defaults, flatpak, system_steps, tools
from dotfiles_setup import install_flow as flow
from dotfiles_setup.log import Logger
from dotfiles_setup.rollback import RollbackLog


def inputs(tmp_path, dry_run=False, euid=1000, packages="vim\n", system="always", upgrade=False, run=None, removals=()):
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    run = run or (lambda *a, **k: SimpleNamespace(returncode=0))
    t =tools.Tooling(Logger(dry_run=dry_run, verbosity=1), home, run=run)
    return flow.FlowInputs(
        t, tmp_path / "repo", "work", frozenset(packages.split()), None, False, "T1", euid=euid, system=system,
        upgrade=upgrade, removals=removals,
    )


class Machine:
    def __init__(self, failing=(), installed="htop"):
        self.commands = []
        self.failing = tuple(failing)
        self.installed = installed.split()

    def __call__(self, argv, **kwargs):
        self.commands.append(list(argv))
        if argv[0] == "dpkg-query":
            listing = "".join(f"ii  {name}\n" for name in self.installed)
            return SimpleNamespace(returncode=0, stdout=listing, stderr="")
        if argv[:3] == ["apt-get", "-s", "remove"]:
            return SimpleNamespace(returncode=0, stdout=f"Remv {argv[-1]} [1]\n", stderr="")
        if argv[:3] == ["flatpak", "info", "--user"]:
            return SimpleNamespace(returncode=0 if argv[3] == "b.B" else 1, stdout="", stderr="")
        failed = any(argv[: len(p)] == list(p) for p in self.failing)
        return SimpleNamespace(returncode=1 if failed else 0, stdout="", stderr="")

    def ran(self, *prefix):
        return any(c[: len(prefix)] == list(prefix) for c in self.commands)

    def index(self, *prefix):
        return next(i for i, c in enumerate(self.commands) if c[: len(prefix)] == list(prefix))


@pytest.fixture(autouse=True)
def has_flatpak(monkeypatch):
    monkeypatch.setattr(flatpak.shutil, "which", lambda name: "/usr/bin/flatpak")


def run_removal_steps(tmp_path, machine, dry_run=False, packages="vim flatpak:a.A"):
    flow_inputs = inputs(tmp_path, dry_run=dry_run, run=machine, packages=packages, removals=("htop", "flatpak:b.B"))
    steps = dict(flow.build_steps(flow_inputs, flow_inputs.packages, RollbackLog(tmp_path / "log")))
    for name in ("install_flatpaks", "remove_flatpaks", "remove_apt_packages"):
        steps[name]()
    return flow_inputs


@pytest.fixture
def no_sudo(monkeypatch):
    monkeypatch.setattr(flow.SudoSession, "start", lambda self: True)


def test_steps_run_in_the_order_the_shell_installer_used(tmp_path):
    steps = flow.build_steps(inputs(tmp_path), frozenset(), RollbackLog(tmp_path / "log"))
    assert [name for name, _ in steps] == [
        "install_core_deps", "disable_snapd", "strip_snap_from_system_path", "configure_apt_sources",
        "install_tools", "install_packages", "report_upgradable", "install_flatpaks", "remove_flatpaks", "remove_apt_packages",
        "report_unremoved", "install_post_apt_tools",
        "enable_gpaste_extension",
        "install_github_bins", "configure_docker_group", "configure_dotfiles", "retire_claude_profile",
        "configure_claude_tools", "change_shell", "set_default_terminal",
    ]


def test_the_install_refuses_to_run_as_root(tmp_path, capsys):
    result = flow.run_install(inputs(tmp_path, euid=0))
    assert not result.succeeded
    assert "must not be run as root" in capsys.readouterr().err


def test_a_failed_sudo_prompt_fails_before_any_step(tmp_path, monkeypatch):
    monkeypatch.setattr(flow.SudoSession, "start", lambda self: False)
    monkeypatch.setattr(flow, "build_steps", lambda *a: pytest.fail("no step may run"))
    assert not flow.run_install(inputs(tmp_path)).succeeded


def test_a_step_returning_false_stops_the_run_and_offers_a_rollback(tmp_path, no_sudo, monkeypatch):
    ran = []
    steps = [("one", lambda: ran.append(1)), ("two", lambda: False), ("three", lambda: ran.append(3))]
    monkeypatch.setattr(flow, "build_steps", lambda *a: steps)
    result = flow.run_install(inputs(tmp_path))
    assert (result.succeeded, result.rollback_pending, ran) == (False, True, [1])
    assert "Step 'two' failed" in result.stdout


def test_steps_returning_none_or_true_let_the_run_continue(tmp_path, no_sudo, monkeypatch):
    steps = [("none", lambda: None), ("true", lambda: True)]
    monkeypatch.setattr(flow, "build_steps", lambda *a: steps)
    assert flow.run_install(inputs(tmp_path)).succeeded


def test_entries_from_an_unfinished_run_are_kept_and_the_log_is_removed_on_success(tmp_path, no_sudo, monkeypatch):
    log = RollbackLog.for_home(tmp_path / "home")
    (tmp_path / "home").mkdir()
    log.path.write_text("STOW_HOME:earlier\n")
    seen = {}
    monkeypatch.setattr(flow, "build_steps", lambda *a: [("peek", lambda: seen.update(entries=log.entries()))])
    assert flow.run_install(inputs(tmp_path)).succeeded
    assert seen["entries"] == ["STOW_HOME:earlier"]
    assert not log.path.exists()


def test_a_failed_run_after_an_unfinished_one_keeps_both_runs_entries(tmp_path, no_sudo, monkeypatch):
    log = RollbackLog.for_home(tmp_path / "home")
    (tmp_path / "home").mkdir()
    log.path.write_text("STOW_HOME:earlier\n")
    steps = [("track", lambda: log.track("STOW_HOME:now", dry_run=False)), ("fail", lambda: False)]
    monkeypatch.setattr(flow, "build_steps", lambda *a: steps)
    flow.run_install(inputs(tmp_path))
    assert log.entries() == ["STOW_HOME:earlier", "STOW_HOME:now"]


def test_the_rollback_log_survives_a_failed_run(tmp_path, no_sudo, monkeypatch):
    log = RollbackLog.for_home(tmp_path / "home")
    monkeypatch.setattr(flow, "build_steps", lambda *a: [("track", lambda: log.track("STOW_HOME:a", dry_run=False)),
                                                         ("fail", lambda: False)])
    flow.run_install(inputs(tmp_path))
    assert log.entries() == ["STOW_HOME:a"]


def test_a_dry_run_writes_no_log_and_never_offers_a_rollback(tmp_path, no_sudo, monkeypatch):
    monkeypatch.setattr(flow, "build_steps", lambda *a: [("fail", lambda: False)])
    result = flow.run_install(inputs(tmp_path, dry_run=True))
    assert not result.rollback_pending
    assert not RollbackLog.for_home(tmp_path / "home").path.exists()


def test_an_interrupt_offers_a_rollback_with_the_conventional_exit_code(tmp_path, no_sudo, monkeypatch):
    def interrupt():
        raise KeyboardInterrupt

    monkeypatch.setattr(flow, "build_steps", lambda *a: [("slow", interrupt)])
    result = flow.run_install(inputs(tmp_path))
    assert (result.returncode, result.rollback_pending) == (130, True)


def test_the_user_bin_dir_is_on_path_during_the_steps_and_restored_after(tmp_path, no_sudo, monkeypatch):
    monkeypatch.setenv("PATH", "/usr/bin")
    seen = {}
    monkeypatch.setattr(flow, "build_steps", lambda *a: [("peek", lambda: seen.update(path=os.environ["PATH"]))])
    flow.run_install(inputs(tmp_path))
    assert seen["path"] == f"{tmp_path / 'home/.local/bin'}:/usr/bin"
    assert os.environ["PATH"] == "/usr/bin"


def test_the_path_is_restored_when_a_step_raises(tmp_path, no_sudo, monkeypatch):
    monkeypatch.setenv("PATH", "/usr/bin")

    def boom():
        raise RuntimeError("step blew up")

    monkeypatch.setattr(flow, "build_steps", lambda *a: [("boom", boom)])
    flow_inputs = inputs(tmp_path)
    with pytest.raises(RuntimeError):
        flow.run_install(flow_inputs)
    assert os.environ["PATH"] == "/usr/bin"


def test_the_sudo_refresh_loop_always_stops(tmp_path, monkeypatch):
    stops = []
    monkeypatch.setattr(flow.SudoSession, "start", lambda self: True)
    monkeypatch.setattr(flow.SudoSession, "stop", lambda self: stops.append(1))
    monkeypatch.setattr(flow, "build_steps", lambda *a: [("fail", lambda: False)])
    flow.run_install(inputs(tmp_path))
    assert stops == [1]


def test_the_steps_receive_the_resolved_package_names(tmp_path, no_sudo, monkeypatch):
    seen = {}

    def build(inputs_, packages, log):
        seen["packages"] = packages
        return []

    monkeypatch.setattr(flow, "build_steps", build)
    flow.run_install(inputs(tmp_path, packages="vim\ngit\n"))
    assert seen["packages"] == frozenset({"vim", "git"})


def _recorded_steps(monkeypatch):
    ran = []
    steps = [(name, lambda name=name: ran.append(name)) for name in ("install_packages", "configure_dotfiles")]
    monkeypatch.setattr(flow, "build_steps", lambda *a: steps)
    return ran


def _no_sudo_prompt(monkeypatch):
    monkeypatch.setattr(flow.SudoSession, "start", lambda self: pytest.fail("sudo must not be requested"))


def test_auto_skips_the_system_steps_and_the_sudo_prompt_when_nothing_is_pending(tmp_path, monkeypatch):
    ran = _recorded_steps(monkeypatch)
    _no_sudo_prompt(monkeypatch)
    monkeypatch.setattr(flow, "system_stage_reasons", lambda ctx: [])
    assert flow.run_install(inputs(tmp_path, system="auto")).succeeded
    assert ran == ["configure_dotfiles"]


def test_auto_runs_the_system_steps_when_the_check_finds_work(tmp_path, no_sudo, monkeypatch):
    ran = _recorded_steps(monkeypatch)
    monkeypatch.setattr(flow, "system_stage_reasons", lambda ctx: ["2 apt package(s) not installed"])
    assert flow.run_install(inputs(tmp_path, system="auto")).succeeded
    assert ran == ["install_packages", "configure_dotfiles"]


@pytest.fixture
def settled_machine(tmp_path, monkeypatch):
    nosnap = tmp_path / "nosnap.pref"
    nosnap.write_text("Package: snapd\n")
    real_check = flow.system_stage_reasons
    monkeypatch.setattr(flow, "system_stage_reasons", lambda ctx: real_check(ctx, nosnap))
    monkeypatch.setattr(system_steps, "docker_group_pending", lambda ctx: False)
    monkeypatch.setattr(desktop_defaults, "shell_change_pending", lambda: False)
    return Machine(installed="htop vim")


def test_auto_starts_the_system_stage_for_an_approved_installed_apt_removal(
    tmp_path, no_sudo, monkeypatch, settled_machine,
):
    ran = _recorded_steps(monkeypatch)
    flow_inputs = inputs(tmp_path, system="auto", run=settled_machine, removals=("htop",))
    assert flow.run_install(flow_inputs).succeeded
    assert ran == ["install_packages", "configure_dotfiles"]


def test_auto_skips_the_system_stage_when_removals_were_declined(tmp_path, monkeypatch, settled_machine):
    ran = _recorded_steps(monkeypatch)
    _no_sudo_prompt(monkeypatch)
    assert flow.run_install(inputs(tmp_path, system="auto", run=settled_machine)).succeeded
    assert ran == ["configure_dotfiles"]


@pytest.mark.parametrize("system", ["never", "auto"])
def test_apt_removals_without_the_system_stage_warn(tmp_path, monkeypatch, capsys, system):
    _recorded_steps(monkeypatch)
    _no_sudo_prompt(monkeypatch)
    monkeypatch.setattr(flow, "system_stage_reasons", lambda ctx: [])
    flow_inputs = inputs(tmp_path, system=system, removals=("github:derailed/k9s", "flatpak:b.B"))
    assert flow.run_install(flow_inputs).succeeded
    assert "apt removals skipped: system stage not run (use --system)" in capsys.readouterr().out
    assert flow_inputs.removed == []


def test_no_apt_removal_warning_for_flatpak_only_removals(tmp_path, monkeypatch, capsys):
    _recorded_steps(monkeypatch)
    flow_inputs = inputs(tmp_path, system="never", removals=("flatpak:b.B",))
    assert flow.run_install(flow_inputs).succeeded
    assert "apt removals skipped" not in capsys.readouterr().out


def test_always_runs_the_system_steps_without_checking(tmp_path, no_sudo, monkeypatch):
    ran = _recorded_steps(monkeypatch)
    monkeypatch.setattr(flow, "system_stage_reasons", lambda ctx: pytest.fail("no check when forced"))
    assert flow.run_install(inputs(tmp_path, system="always")).succeeded
    assert ran == ["install_packages", "configure_dotfiles"]


def test_never_skips_the_system_steps_without_checking_or_prompting(tmp_path, monkeypatch):
    ran = _recorded_steps(monkeypatch)
    _no_sudo_prompt(monkeypatch)
    monkeypatch.setattr(flow, "system_stage_reasons", lambda ctx: pytest.fail("no check when skipped"))
    assert flow.run_install(inputs(tmp_path, system="never")).succeeded
    assert ran == ["configure_dotfiles"]


def test_upgrade_replaces_the_report_with_the_upgrade_step(tmp_path):
    steps = flow.build_steps(inputs(tmp_path, upgrade=True), frozenset(), RollbackLog(tmp_path / "log"))
    names = [name for name, _ in steps]
    assert "upgrade_packages" in names
    assert "report_upgradable" not in names
    assert names.index("upgrade_packages") == names.index("install_packages") + 1


@pytest.mark.parametrize("upgrade", [True, False])
def test_install_tools_step_receives_the_upgrade_flag(tmp_path, monkeypatch, upgrade):
    seen = []
    monkeypatch.setattr(tools, "install_tools", lambda t, packages, upgrade=False: seen.append(upgrade) or True)
    steps = dict(flow.build_steps(inputs(tmp_path, upgrade=upgrade), frozenset(), RollbackLog(tmp_path / "log")))
    steps["install_tools"]()
    assert seen == [upgrade]


def test_upgrade_forces_the_system_stage_without_checking(tmp_path, no_sudo, monkeypatch):
    ran = _recorded_steps(monkeypatch)
    monkeypatch.setattr(flow, "system_stage_reasons", lambda ctx: pytest.fail("no check when upgrading"))
    assert flow.run_install(inputs(tmp_path, system="auto", upgrade=True)).succeeded
    assert ran == ["install_packages", "configure_dotfiles"]


def test_every_root_step_is_a_known_step_name(tmp_path):
    names = {
        name for name, _ in flow.build_steps(inputs(tmp_path, upgrade=True), frozenset(), RollbackLog(tmp_path / "log"))
    }
    assert flow.SYSTEM_STEPS <= names


def test_every_root_step_is_known_without_upgrade(tmp_path):
    names = {name for name, _ in flow.build_steps(inputs(tmp_path), frozenset(), RollbackLog(tmp_path / "log"))}
    assert flow.SYSTEM_STEPS - {"upgrade_packages"} <= names


def test_removals_run_in_order_after_flatpak_install(tmp_path):
    machine = Machine()
    flow_inputs = run_removal_steps(tmp_path, machine)
    install = machine.index("flatpak", "install")
    flatpak_removal = machine.index("flatpak", "uninstall")
    apt_removal = machine.index("sudo", "apt-get", "remove", "-y", "htop")
    assert install < flatpak_removal < apt_removal
    assert flow_inputs.removed == ["flatpak:b.B", "htop"]


def _run_removals_and_report(tmp_path, machine, removals, dry_run=False):
    flow_inputs = inputs(tmp_path, dry_run=dry_run, run=machine, packages="vim flatpak:a.A", removals=removals)
    steps = dict(flow.build_steps(flow_inputs, flow_inputs.packages, RollbackLog(tmp_path / "log")))
    for name in ("install_flatpaks", "remove_flatpaks", "remove_apt_packages", "report_unremoved"):
        steps[name]()
    return flow_inputs


def test_entries_left_after_the_removal_steps_are_reported_once(tmp_path, capsys):
    machine = Machine(failing=[("sudo", "apt-get", "remove")])
    _run_removals_and_report(tmp_path, machine, ("htop", "flatpak:b.B", "nvm"))
    out = capsys.readouterr().out
    assert out.count("not removed: htop; they will be offered again next run") == 1
    assert "nvm" not in out.split("not removed:")[1]


def test_nothing_is_reported_when_every_removal_succeeded(tmp_path, capsys):
    _run_removals_and_report(tmp_path, Machine(), ("htop", "flatpak:b.B"))
    assert "not removed" not in capsys.readouterr().out


def test_report_unremoved_is_a_user_step_after_the_removals(tmp_path):
    names = [name for name, _ in flow.build_steps(inputs(tmp_path), frozenset(), RollbackLog(tmp_path / "log"))]
    assert names.index("report_unremoved") == names.index("remove_apt_packages") + 1
    assert "report_unremoved" not in flow.SYSTEM_STEPS


def test_flatpak_failure_skips_all_removals(tmp_path):
    machine = Machine(failing=[("flatpak", "install")])
    flow_inputs = run_removal_steps(tmp_path, machine)
    assert not machine.ran("flatpak", "uninstall")
    assert not machine.ran("sudo")
    assert not machine.ran("apt-get")
    assert flow_inputs.removed == []


def test_dry_run_removals_run_no_command(tmp_path, capsys):
    machine = Machine()
    flow_inputs = run_removal_steps(tmp_path, machine, dry_run=True)
    assert machine.commands == []
    assert flow_inputs.removed == []
    out = capsys.readouterr().out
    assert "Would remove" in out
    assert "htop" in out
    assert "b.B" in out


def test_removed_reports_entry_names(tmp_path):
    machine = Machine(installed="k9s slack-desktop htop")
    entries = ("github:derailed/k9s", "slack-desktop", "htop")
    flow_inputs = inputs(tmp_path, run=machine, removals=entries)
    steps = dict(flow.build_steps(flow_inputs, flow_inputs.packages, RollbackLog(tmp_path / "log")))
    steps["remove_apt_packages"]()
    assert flow_inputs.removed == ["htop", "github:derailed/k9s", "slack-desktop"]
    assert not any("github:derailed/k9s" in c for c in machine.commands)


def test_apt_removal_skips_a_dpkg_name_a_wanted_entry_covers(tmp_path):
    machine = Machine(installed="k9s")
    flow_inputs = inputs(tmp_path, run=machine, packages="k9s", removals=("github:derailed/k9s",))
    dict(flow.build_steps(flow_inputs, flow_inputs.packages, RollbackLog(tmp_path / "log")))["remove_apt_packages"]()
    assert not machine.ran("apt-get")
    assert not machine.ran("sudo")
    assert flow_inputs.removed == []


def test_removed_pin_tracks_a_deb_undo_entry(tmp_path):
    machine = Machine(installed="k9s")
    flow_inputs = inputs(tmp_path, run=machine, removals=("github:derailed/k9s",))
    log = RollbackLog(tmp_path / "log")
    dict(flow.build_steps(flow_inputs, flow_inputs.packages, log))["remove_apt_packages"]()
    assert log.entries() == ["DEB_REMOVED:k9s"]


def test_dry_run_announces_pins_by_entry(tmp_path, capsys):
    flow_inputs = inputs(tmp_path, dry_run=True, removals=("github:derailed/k9s",))
    steps = dict(flow.build_steps(flow_inputs, flow_inputs.packages, RollbackLog(tmp_path / "log")))
    steps["remove_apt_packages"]()
    assert "Would remove apt package github:derailed/k9s" in capsys.readouterr().out


def test_flatpak_failure_warns_once_at_default_verbosity(tmp_path, capsys):
    machine = Machine(failing=[("flatpak", "install")])
    flow_inputs = inputs(tmp_path, run=machine, packages="flatpak:a.A", removals=("htop",))
    quiet = flow.FlowInputs(**{**vars(flow_inputs), "t": tools.Tooling(Logger(dry_run=False), flow_inputs.t.home, run=machine)})
    steps = dict(flow.build_steps(quiet, quiet.packages, RollbackLog(tmp_path / "log")))
    for name in ("install_flatpaks", "remove_flatpaks", "remove_apt_packages"):
        steps[name]()
    assert capsys.readouterr().out.count("Skipping removals: a Flatpak install failed") == 1


def test_manual_removals_are_left_to_the_prompt_and_not_run(tmp_path, capsys):
    machine = Machine()
    flow_inputs = inputs(tmp_path, run=machine, removals=("nvm",))
    steps = dict(flow.build_steps(flow_inputs, flow_inputs.packages, RollbackLog(tmp_path / "log")))
    steps["remove_apt_packages"]()
    assert "remove manually" not in capsys.readouterr().out
    assert machine.commands == []


def test_remove_apt_packages_is_a_system_step():
    assert "remove_apt_packages" in flow.SYSTEM_STEPS


def test_the_banner_differs_for_a_dry_run(tmp_path, capsys):
    flow.print_completion_banner(Logger(dry_run=True, verbosity=0))
    assert "Dry-run complete! No changes were made." in capsys.readouterr().out
    flow.print_completion_banner(Logger(dry_run=False, verbosity=0))
    out = capsys.readouterr().out
    assert "Setup complete!" in out
    assert "secrets.env" in out
