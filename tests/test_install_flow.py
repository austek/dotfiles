from types import SimpleNamespace

import pytest
from dotfiles_setup import install_flow as flow
from dotfiles_setup import tools
from dotfiles_setup.log import Logger
from dotfiles_setup.rollback import RollbackLog


def inputs(tmp_path, dry_run=False, euid=1000, packages="vim\n"):
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    package_file = tmp_path / "packages.txt"
    package_file.write_text(packages)
    t = tools.Tooling(Logger(dry_run=dry_run, verbosity=1), home, run=lambda *a, **k: SimpleNamespace(returncode=0))
    return flow.FlowInputs(t, tmp_path / "repo", "work", package_file, None, False, tmp_path / "profiles", "T1", euid=euid)


@pytest.fixture
def no_sudo(monkeypatch):
    monkeypatch.setattr(flow.SudoSession, "start", lambda self: True)


def test_steps_run_in_the_order_the_shell_installer_used(tmp_path):
    steps = flow.build_steps(inputs(tmp_path), frozenset(), RollbackLog(tmp_path / "log"))
    assert [name for name, _ in steps] == [
        "install_core_deps", "disable_snapd", "strip_snap_from_system_path", "configure_apt_sources",
        "install_tools", "install_packages", "install_post_apt_tools", "enable_gpaste_extension",
        "install_github_bins", "configure_docker_group", "configure_dotfiles", "configure_claude_profile",
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


def test_the_sudo_refresh_loop_always_stops(tmp_path, monkeypatch):
    stops = []
    monkeypatch.setattr(flow.SudoSession, "start", lambda self: True)
    monkeypatch.setattr(flow.SudoSession, "stop", lambda self: stops.append(1))
    monkeypatch.setattr(flow, "build_steps", lambda *a: [("fail", lambda: False)])
    flow.run_install(inputs(tmp_path))
    assert stops == [1]


def test_the_package_names_come_from_the_resolved_file(tmp_path, no_sudo, monkeypatch):
    seen = {}

    def build(inputs_, packages, log):
        seen["packages"] = packages
        return []

    monkeypatch.setattr(flow, "build_steps", build)
    flow.run_install(inputs(tmp_path, packages="# c\nvim\n\ngit\n"))
    assert seen["packages"] == frozenset({"vim", "git"})


def test_the_banner_differs_for_a_dry_run(tmp_path, capsys):
    flow.print_completion_banner(Logger(dry_run=True, verbosity=0))
    assert "Dry-run complete! No changes were made." in capsys.readouterr().out
    flow.print_completion_banner(Logger(dry_run=False, verbosity=0))
    out = capsys.readouterr().out
    assert "Setup complete!" in out
    assert "secrets.env" in out
