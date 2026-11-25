from dataclasses import replace
from types import SimpleNamespace

import pytest
from dotfiles_setup import flatpak, tools
from dotfiles_setup import install_flow as flow
from dotfiles_setup.log import Logger
from dotfiles_setup.plan_types import StepPlan
from dotfiles_setup.rollback import RollbackLog
from dotfiles_setup.step_plans import STEP_ROWS, UNKNOWN_ROWS
from dotfiles_setup.system_steps import SystemContext


def _inputs(tmp_path, plans=(), dry_run=False, system="always", run=None, packages=("vim", "curl")):
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    run = run or (lambda *a, **k: SimpleNamespace(returncode=0, stdout="", stderr=""))
    t = tools.Tooling(Logger(dry_run=dry_run), home, run=run)
    return flow.FlowInputs(
        t, tmp_path / "repo", "work", frozenset(packages), None, False, "T1", euid=1000, system=system, plans=plans,
    )


def _steps(inputs, tmp_path):
    return dict(flow.build_steps(inputs, inputs.packages, RollbackLog(tmp_path / "log")))


@pytest.fixture(autouse=True)
def has_flatpak(monkeypatch):
    monkeypatch.setattr(flatpak.shutil, "which", lambda name: "/usr/bin/flatpak")


def test_the_apt_step_installs_the_planned_packages_only(tmp_path):
    commands = []

    def run(argv, **kwargs):
        commands.append(list(argv))
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    plans = (StepPlan("apt", 2, 1, install=("curl",)),)
    _steps(_inputs(tmp_path, plans, run=run), tmp_path)["install_packages"]()
    install = next(c for c in commands if "install" in c and "apt-get" in c)
    assert install[-1] == "curl"
    assert "vim" not in install


def test_the_flatpak_step_installs_the_planned_apps_without_checking_again(tmp_path):
    commands = []

    def run(argv, **kwargs):
        commands.append(list(argv))
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    plans = (StepPlan("flatpak", 1, 0, install=("a.A",)),)
    inputs = _inputs(tmp_path, plans, run=run, packages=("flatpak:a.A",))
    _steps(inputs, tmp_path)["install_flatpaks"]()
    assert not any(c[:2] == ["flatpak", "info"] for c in commands)
    assert any(c[:3] == ["flatpak", "install", "--user"] and c[-1] == "a.A" for c in commands)


def _run_names(inputs, monkeypatch):
    ran = []
    monkeypatch.setattr(flow, "_run_steps", lambda steps, logger, log: ran.extend(n for n, _ in steps) or flow.InstallResult(True, 0, ""))
    monkeypatch.setattr(flow.SudoSession, "start", lambda self: True)
    flow.run_install(inputs)
    return set(ran)


def test_a_dry_run_with_a_plan_runs_only_the_steps_whose_row_is_unknown(tmp_path, monkeypatch):
    plans = tuple(StepPlan(row, 0, 0, known=False) for row in UNKNOWN_ROWS) + (StepPlan("apt", 0, 0),)
    ran = _run_names(_inputs(tmp_path, plans, dry_run=True), monkeypatch)
    assert ran == {step for step, row in STEP_ROWS.items() if row in UNKNOWN_ROWS}


def test_a_dry_run_without_a_plan_runs_every_step(tmp_path, monkeypatch):
    inputs = _inputs(tmp_path, dry_run=True)
    ran = _run_names(inputs, monkeypatch)
    assert ran == {name for name, _ in flow.build_steps(inputs, inputs.packages, RollbackLog(tmp_path / "log"))}


def test_a_real_run_with_a_plan_still_runs_every_step(tmp_path, monkeypatch):
    plans = tuple(StepPlan(row, 0, 0, known=False) for row in UNKNOWN_ROWS)
    inputs = _inputs(tmp_path, plans)
    ran = _run_names(inputs, monkeypatch)
    assert ran == {name for name, _ in flow.build_steps(inputs, inputs.packages, RollbackLog(tmp_path / "log"))}


def _wanted(inputs, tmp_path):
    ctx = SystemContext(inputs.t, inputs.dotfiles_dir, inputs.packages, RollbackLog(tmp_path / "log"))
    return flow._system_stage_wanted(replace(inputs, system="auto"), ctx)


def test_the_system_stage_runs_when_a_sudo_row_has_a_reason(tmp_path):
    plans = (StepPlan("apt", 1, 0, install=("vim",), needs_sudo=True, reason="1 apt package(s) not installed (vim...)"),)
    assert _wanted(_inputs(tmp_path, plans), tmp_path)


def test_the_system_stage_is_skipped_when_no_sudo_row_has_a_reason(tmp_path, capsys):
    plans = (StepPlan("apt", 1, 1, needs_sudo=True), StepPlan("secrets.env", 0, 0, change=("create x",)))
    assert not _wanted(_inputs(tmp_path, plans), tmp_path)


def _uninstall_inputs(tmp_path, listed, prune, commands):
    def run(argv, **kwargs):
        commands.append(list(argv))
        out = "serena-agent v1\n" if argv[:3] == ["uv", "tool", "list"] else ""
        return SimpleNamespace(returncode=0, stdout=out, stderr="")

    (tmp_path / "repo/packages").mkdir(parents=True)
    (tmp_path / "repo/packages/uninstall.txt").write_text(listed)
    return replace(_inputs(tmp_path, run=run), prune=prune)


def test_the_uninstall_step_removes_nothing_without_prune(tmp_path):
    commands = []
    _steps(_uninstall_inputs(tmp_path, "serena\n", False, commands), tmp_path)["uninstall_tools"]()
    assert not any(c[:3] == ["uv", "tool", "uninstall"] for c in commands)


def test_the_uninstall_step_removes_pending_names_with_prune_and_says_data_cannot_be_restored(tmp_path, capsys):
    commands = []
    _steps(_uninstall_inputs(tmp_path, "serena\n", True, commands), tmp_path)["uninstall_tools"]()
    assert ["uv", "tool", "uninstall", "serena-agent"] in commands
    assert "cannot be restored" in capsys.readouterr().out


def test_the_uninstall_step_warns_for_an_unknown_entry_and_never_fails(tmp_path, capsys):
    commands = []
    result = _steps(_uninstall_inputs(tmp_path, "nope\n", True, commands), tmp_path)["uninstall_tools"]()
    assert result is None
    assert "nope" in capsys.readouterr().out
    assert not any(c[:3] == ["uv", "tool", "uninstall"] for c in commands)
