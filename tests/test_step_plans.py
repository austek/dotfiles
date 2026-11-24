from types import SimpleNamespace

import pytest
from dotfiles_setup.log import Logger
from dotfiles_setup.step_plans import STEP_ROWS, UNKNOWN_ROWS, build_step_plans
from dotfiles_setup.tooling import Tooling

WRITE_VERBS = {"sudo", "apt-get", "dpkg", "rm", "mv", "cp", "ln", "tee", "mkdir", "touch", "stow", "chmod"}
READ_ONLY_APT_GET = ("apt-get", "-s")


def _machine(monkeypatch, apt=(), flatpaks=(), upgradable=()):
    calls = []

    def run(argv, **kwargs):
        calls.append(list(argv))
        if argv[0] == "dpkg-query":
            out = "".join(f"ii  {name} 1.0\n" for name in apt)
        elif argv[:3] == ["apt-get", "-s", "dist-upgrade"]:
            out = "".join(f"Inst {name} [1.0] (2.0 x)\n" for name in upgradable)
        else:
            out = ""
        code = 0 if argv[:3] != ["flatpak", "info", "--user"] or argv[3] in flatpaks else 1
        return SimpleNamespace(returncode=code, stdout=out, stderr="")

    monkeypatch.setattr("dotfiles_setup.tooling.subprocess.run", run)
    monkeypatch.setattr("dotfiles_setup.flatpak.shutil.which", lambda name: "/usr/bin/" + name)
    return calls


def _plans(tmp_path, wanted, *, pending=(), upgrade=False, prune=False, system="auto"):
    dotfiles = tmp_path / "dotfiles"
    (dotfiles / "packages").mkdir(parents=True, exist_ok=True)
    t = Tooling(Logger(dry_run=False), tmp_path)
    plans = build_step_plans(
        t, dotfiles, frozenset(wanted), tuple(pending), upgrade=upgrade, prune=prune, system=system,
        overlay_root=None, preset_name="work",
    )
    return {plan.step: plan for plan in plans}


def test_apt_lists_the_wanted_packages_that_are_not_installed(tmp_path, monkeypatch):
    _machine(monkeypatch, apt=("zsh",))
    plan = _plans(tmp_path, {"zsh", "curl", "jq"})["apt"]
    assert plan.install == ("curl", "jq")
    assert (plan.wanted, plan.installed) == (3, 1)


def test_apt_ignores_flatpak_and_pin_entries(tmp_path, monkeypatch):
    _machine(monkeypatch)
    plan = _plans(tmp_path, {"zsh", "flatpak:org.x.App", "github:a/b"})["apt"]
    assert plan.install == ("zsh",)


def test_flatpak_lists_the_missing_apps(tmp_path, monkeypatch):
    _machine(monkeypatch, flatpaks=("org.a.A",))
    plan = _plans(tmp_path, {"flatpak:org.a.A", "flatpak:org.b.B"})["flatpak"]
    assert plan.install == ("org.b.B",)
    assert (plan.wanted, plan.installed) == (2, 1)


def test_flatpak_is_skipped_when_the_skip_variable_is_set(tmp_path, monkeypatch):
    _machine(monkeypatch)
    monkeypatch.setenv("DOTFILES_SKIP_FLATPAK", "1")
    plan = _plans(tmp_path, {"flatpak:org.b.B"})["flatpak"]
    assert plan.install == ()
    assert "DOTFILES_SKIP_FLATPAK" in plan.note


def test_github_debs_list_the_pending_pins(tmp_path, monkeypatch):
    _machine(monkeypatch)
    (tmp_path / "dotfiles" / "packages").mkdir(parents=True)
    (tmp_path / "dotfiles" / "packages" / "github_bins.txt").write_text("derailed/k9s 0.50.0 k9s_linux_amd64.deb\n")
    plan = _plans(tmp_path, {"github:derailed/k9s"})["github debs"]
    assert plan.install == ("k9s_linux_amd64.deb",)


def test_removals_are_held_back_unless_prune_is_set(tmp_path, monkeypatch):
    _machine(monkeypatch)
    without = _plans(tmp_path, set(), pending=("htop",))["removals"]
    with_prune = _plans(tmp_path, set(), pending=("htop",), prune=True)["removals"]
    assert (without.remove, without.held) == ((), ("htop",))
    assert (with_prune.remove, with_prune.held) == (("htop",), ())


def test_manual_entries_are_not_removals(tmp_path, monkeypatch):
    _machine(monkeypatch)
    plan = _plans(tmp_path, set(), pending=("htop", "sdkman"), prune=True)["removals"]
    assert plan.remove == ("htop",)
    assert plan.held == ()


def test_flatpak_removals_still_run_under_no_system(tmp_path, monkeypatch):
    _machine(monkeypatch)
    plan = _plans(tmp_path, set(), pending=("htop", "flatpak:org.x.App"), prune=True, system="never")["removals"]
    assert plan.remove == ("flatpak:org.x.App",)


def test_upgrade_makes_the_flatpak_update_a_change(tmp_path, monkeypatch):
    _machine(monkeypatch, flatpaks=("org.a.A",))
    assert _plans(tmp_path, {"flatpak:org.a.A"}, upgrade=True)["flatpak"].change == ("update all Flatpak apps",)
    assert _plans(tmp_path, {"flatpak:org.a.A"})["flatpak"].change == ()


def test_the_flatpak_update_is_still_a_change_under_no_system_because_it_is_a_user_step(tmp_path, monkeypatch):
    _machine(monkeypatch, flatpaks=("org.a.A",))
    assert _plans(tmp_path, {"flatpak:org.a.A"}, upgrade=True, system="never")["flatpak"].change


def test_no_flatpak_update_is_planned_when_flatpak_is_skipped(tmp_path, monkeypatch):
    _machine(monkeypatch)
    monkeypatch.setenv("DOTFILES_SKIP_FLATPAK", "1")
    assert _plans(tmp_path, {"flatpak:org.a.A"}, upgrade=True)["flatpak"].change == ()


def test_upgrade_rows_appear_only_with_upgrade(tmp_path, monkeypatch):
    _machine(monkeypatch, upgradable=("curl",))
    assert _plans(tmp_path, set())["apt"].upgrade == ()
    assert _plans(tmp_path, set(), upgrade=True)["apt"].upgrade == ("curl",)


def test_no_system_leaves_the_sudo_rows_without_work(tmp_path, monkeypatch):
    _machine(monkeypatch)
    plans = _plans(tmp_path, {"zsh"}, pending=("htop",), system="never")
    assert plans["apt"].install == ()
    assert "--no-system" in plans["apt"].note
    assert plans["removals"].remove == ()


def test_the_steps_that_cannot_be_checked_are_listed_as_unknown_with_a_note(tmp_path, monkeypatch):
    _machine(monkeypatch)
    plans = _plans(tmp_path, set())
    unknown = {step: plan for step, plan in plans.items() if not plan.known}
    assert set(unknown) == set(UNKNOWN_ROWS)
    assert all(plan.note for plan in unknown.values())


def test_every_apply_step_maps_to_a_plan_row(tmp_path, monkeypatch):
    from dotfiles_setup import install_flow
    from dotfiles_setup.rollback import RollbackLog

    _machine(monkeypatch)
    names = set()
    for upgrade in (False, True):
        inputs = install_flow.FlowInputs(
            Tooling(Logger(dry_run=False), tmp_path), tmp_path, "work", frozenset(), None, False, "s", upgrade=upgrade,
        )
        names |= {name for name, _ in install_flow.build_steps(inputs, frozenset(), RollbackLog(tmp_path / "log"))}
    assert names == set(STEP_ROWS)
    rows = set(_plans(tmp_path, set(), system="always", upgrade=True)) | {"overlay"}
    assert set(STEP_ROWS.values()) <= rows


def test_sudo_rows_carry_the_system_stage_reason(tmp_path, monkeypatch):
    _machine(monkeypatch)
    apt = _plans(tmp_path, {"zsh"})["apt"]
    assert apt.needs_sudo
    assert apt.reason == "1 apt package(s) not installed (zsh...)"


def test_no_system_leaves_no_reasons(tmp_path, monkeypatch):
    _machine(monkeypatch)
    plans = _plans(tmp_path, {"zsh"}, system="never")
    assert [p for p in plans.values() if p.reason] == []


def test_the_user_tools_row_lists_the_missing_installers(tmp_path, monkeypatch):
    _machine(monkeypatch)
    monkeypatch.setattr("dotfiles_setup.release_installers.platform.machine", lambda: "aarch64")
    assert _plans(tmp_path, {"oh-my-zsh", "sdkman"})["user tools"].install == ("oh-my-zsh", "sdkman")


def test_the_secrets_row_asks_for_the_missing_file(tmp_path, monkeypatch):
    _machine(monkeypatch)
    row = _plans(tmp_path, set())["secrets.env"]
    assert row.change == (f"create {tmp_path / '.config/dotfiles/secrets.env'}",)


def test_the_dotfiles_row_lists_unlinked_packages(tmp_path, monkeypatch):
    _machine(monkeypatch)
    (tmp_path / "dotfiles" / "zsh").mkdir(parents=True)
    (tmp_path / "dotfiles" / "zsh" / ".zshrc").write_text("")
    (tmp_path / "dotfiles" / ".stow-packages").write_text("zsh\n")
    assert _plans(tmp_path, set())["dotfiles links"].change == ("link zsh",)


@pytest.mark.parametrize("scenario", [
    {"apt": (), "wanted": {"zsh"}},
    {"apt": ("zsh", "snapd"), "wanted": {"zsh"}},
    {"apt": ("zsh",), "wanted": {"zsh"}},
])
def test_stage_reasons_from_the_plan_equal_the_direct_check(tmp_path, monkeypatch, scenario):
    from dotfiles_setup.rollback import RollbackLog
    from dotfiles_setup.system_check import system_stage_reasons
    from dotfiles_setup.system_steps import SystemContext

    _machine(monkeypatch, apt=scenario["apt"])
    (tmp_path / "dotfiles" / "packages").mkdir(parents=True, exist_ok=True)
    plans = tuple(_plans(tmp_path, scenario["wanted"]).values())
    ctx = SystemContext(Tooling(Logger(dry_run=False), tmp_path), tmp_path / "dotfiles", scenario["wanted"], RollbackLog(tmp_path / "log"))
    assert system_stage_reasons(ctx, plans=plans) == system_stage_reasons(ctx)


def test_planning_is_read_only(tmp_path, monkeypatch):
    calls = _machine(monkeypatch, apt=("zsh",), flatpaks=("org.a.A",), upgradable=("curl",))
    before = sorted(p.relative_to(tmp_path) for p in tmp_path.rglob("*") if "dotfiles" not in p.parts)
    _plans(tmp_path, {"zsh", "curl", "flatpak:org.a.A"}, pending=("htop",), upgrade=True)
    after = sorted(p.relative_to(tmp_path) for p in tmp_path.rglob("*") if "dotfiles" not in p.parts)
    assert before == after
    writes = [c for c in calls if c[0] in WRITE_VERBS and tuple(c[:2]) != READ_ONLY_APT_GET]
    writes += [c for c in calls if c[0] == "flatpak" and c[:3] != ["flatpak", "info", "--user"]]
    assert writes == []


@pytest.mark.parametrize("system", ["auto", "always"])
def test_system_modes_plan_the_sudo_rows(tmp_path, monkeypatch, system):
    _machine(monkeypatch)
    assert _plans(tmp_path, {"zsh"}, system=system)["apt"].install == ("zsh",)


def test_upgrade_is_a_change_even_when_the_local_cache_lists_nothing(tmp_path, monkeypatch):
    _machine(monkeypatch, apt=("zsh",))
    plan = _plans(tmp_path, {"zsh"}, upgrade=True)["apt"]
    assert plan.upgrade == ()
    assert plan.change


def test_no_upgrade_means_no_upgrade_change(tmp_path, monkeypatch):
    _machine(monkeypatch, apt=("zsh",))
    assert _plans(tmp_path, {"zsh"})["apt"].change == ()


def test_a_pending_overlay_move_is_not_a_change_while_stow_is_missing(tmp_path, monkeypatch):
    from dotfiles_setup import overlay

    _machine(monkeypatch)
    overlay.LEGACY_OVERLAY_ROOT.mkdir()
    monkeypatch.setattr("dotfiles_setup.step_plans.shutil.which", lambda name: None)
    plan = _plans(tmp_path, set())["overlay"]
    assert plan.change == ()
    assert "stow" in plan.note


def test_a_pending_overlay_move_is_a_change_when_stow_is_installed(tmp_path, monkeypatch):
    from dotfiles_setup import overlay

    _machine(monkeypatch)
    overlay.LEGACY_OVERLAY_ROOT.mkdir()
    monkeypatch.setattr("dotfiles_setup.step_plans.shutil.which", lambda name: "/usr/bin/" + name)
    assert _plans(tmp_path, set())["overlay"].change
