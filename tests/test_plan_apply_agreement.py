from types import SimpleNamespace

import pytest
from dotfiles_setup import apt_packages, flatpak
from dotfiles_setup.log import Logger
from dotfiles_setup.rollback import RollbackLog
from dotfiles_setup.step_plans import build_step_plans
from dotfiles_setup.system_steps import SystemContext
from dotfiles_setup.tooling import Tooling

pytestmark = pytest.mark.usefixtures("no_core_packages")


def _machine(monkeypatch, apt=(), flatpaks=(), dpkg_listing=""):
    calls = []

    def run(argv, **kwargs):
        calls.append(list(argv))
        out = ""
        if argv[0] == "dpkg-query":
            out = "".join(f"ii  {name} 1.0\n" for name in apt)
        elif argv[:2] == ["dpkg", "-l"]:
            out = dpkg_listing
        code = 0 if argv[:3] != ["flatpak", "info", "--user"] or argv[3] in flatpaks else 1
        return SimpleNamespace(returncode=code, stdout=out, stderr="")

    monkeypatch.setattr("dotfiles_setup.tooling.subprocess.run", run)
    monkeypatch.setattr("dotfiles_setup.flatpak.shutil.which", lambda name: "/usr/bin/" + name)
    return calls


def _plan(tmp_path, wanted, step, **kwargs):
    dotfiles = tmp_path / "dotfiles"
    (dotfiles / "packages").mkdir(parents=True, exist_ok=True)
    t = Tooling(Logger(dry_run=False), tmp_path)
    plans = build_step_plans(
        t, dotfiles, frozenset(wanted), (), upgrade=False, prune=False, system="auto",
        overlay_root=None, preset_name="work", **kwargs,
    )
    return t, next(plan for plan in plans if plan.step == step)


def _ctx(t, tmp_path, wanted):
    return SystemContext(t, tmp_path / "dotfiles", frozenset(wanted), RollbackLog(tmp_path / "log"))


def test_apt_installs_exactly_what_the_plan_lists(tmp_path, monkeypatch):
    calls = _machine(monkeypatch, apt=("zsh",))
    wanted = {"zsh", "curl", "jq"}
    t, plan = _plan(tmp_path, wanted, "apt")
    calls.clear()
    assert apt_packages.install_packages(_ctx(t, tmp_path, wanted), tmp_path / "sources.d", install=plan.install)
    install = next(c for c in calls if c[:4] == ["sudo", "DEBIAN_FRONTEND=noninteractive", "apt-get", "install"])
    assert tuple(install[5:]) == plan.install == ("curl", "jq")
    assert not any(c[0] == "dpkg-query" for c in calls)


def test_apt_runs_nothing_when_the_plan_is_empty(tmp_path, monkeypatch):
    calls = _machine(monkeypatch, apt=("zsh",))
    t, plan = _plan(tmp_path, {"zsh"}, "apt")
    calls.clear()
    assert apt_packages.install_packages(_ctx(t, tmp_path, {"zsh"}), tmp_path / "sources.d", install=plan.install)
    assert [c for c in calls if "apt-get" in c] == []


def test_apt_leaves_out_packages_whose_source_was_skipped(tmp_path, monkeypatch):
    calls = _machine(monkeypatch)
    wanted = {"zsh", "docker-ce"}
    t, plan = _plan(tmp_path, wanted, "apt")
    ctx = _ctx(t, tmp_path, wanted)
    ctx.skipped.add("docker-ce")
    calls.clear()
    apt_packages.install_packages(ctx, tmp_path / "sources.d", install=plan.install)
    install = next(c for c in calls if c[:4] == ["sudo", "DEBIAN_FRONTEND=noninteractive", "apt-get", "install"])
    assert tuple(install[5:]) == ("zsh",)


def test_without_a_plan_apt_installs_every_wanted_package_as_before(tmp_path, monkeypatch):
    calls = _machine(monkeypatch, apt=("zsh",))
    t, _ = _plan(tmp_path, {"zsh", "curl"}, "apt")
    calls.clear()
    apt_packages.install_packages(_ctx(t, tmp_path, {"zsh", "curl"}), tmp_path / "sources.d")
    install = next(c for c in calls if c[:4] == ["sudo", "DEBIAN_FRONTEND=noninteractive", "apt-get", "install"])
    assert tuple(install[5:]) == ("curl", "zsh")


def test_flatpak_installs_exactly_what_the_plan_lists_without_asking_again(tmp_path, monkeypatch):
    calls = _machine(monkeypatch, flatpaks=("org.a.A",))
    wanted = {"flatpak:org.a.A", "flatpak:org.b.B"}
    t, plan = _plan(tmp_path, wanted, "flatpak")
    calls.clear()
    assert flatpak.install_flatpaks(t, wanted, only=plan.install) == ()
    installs = [c for c in calls if c[:3] == ["flatpak", "install", "--user"]]
    assert [c[-1] for c in installs] == list(plan.install) == ["org.b.B"]
    assert not any(c[:2] == ["flatpak", "info"] for c in calls)


def test_flatpak_does_nothing_for_an_empty_plan(tmp_path, monkeypatch):
    calls = _machine(monkeypatch, flatpaks=("org.a.A",))
    t, plan = _plan(tmp_path, {"flatpak:org.a.A"}, "flatpak")
    calls.clear()
    assert flatpak.install_flatpaks(t, {"flatpak:org.a.A"}, only=plan.install) == ()
    assert calls == []


def test_github_debs_install_exactly_what_the_plan_lists(tmp_path, monkeypatch):
    listing = "ii  k9s 0.50.0 amd64\n"
    _machine(monkeypatch, dpkg_listing=listing)
    packages = tmp_path / "dotfiles" / "packages"
    packages.mkdir(parents=True)
    (packages / "github_bins.txt").write_text(
        "derailed/k9s 0.50.0 k9s_linux_amd64.deb\nowner/tool 1.0.0 tool_1.0.0_amd64.deb\n"
    )
    wanted = {"github:derailed/k9s", "github:owner/tool"}
    t, plan = _plan(tmp_path, wanted, "github debs")
    installed = []
    monkeypatch.setattr(apt_packages, "_install_deb", lambda ctx, repo, version, filename, temp: installed.append(filename))
    apt_packages.install_github_bins(_ctx(t, tmp_path, wanted), only=plan.install)
    assert installed == list(plan.install) == ["tool_1.0.0_amd64.deb"]


def test_a_planned_deb_is_not_installed_over_a_newer_version_that_appeared_after_planning(tmp_path, monkeypatch):
    packages = tmp_path / "dotfiles" / "packages"
    packages.mkdir(parents=True)
    (packages / "github_bins.txt").write_text("owner/tool 1.0.0 tool_1.0.0_amd64.deb\n")
    wanted = {"github:owner/tool"}
    _machine(monkeypatch, dpkg_listing="")
    t, plan = _plan(tmp_path, wanted, "github debs")
    assert plan.install == ("tool_1.0.0_amd64.deb",)

    def newer_now(argv, **kwargs):
        out = "ii  tool 3.0.0 amd64\n" if argv[:2] == ["dpkg", "-l"] else ""
        code = 1 if argv[:2] == ["dpkg", "--compare-versions"] else 0
        return SimpleNamespace(returncode=code, stdout=out, stderr="")

    monkeypatch.setattr("dotfiles_setup.tooling.subprocess.run", newer_now)
    installed = []
    monkeypatch.setattr(apt_packages, "_install_deb", lambda ctx, repo, version, filename, temp: installed.append(filename))
    apt_packages.install_github_bins(_ctx(t, tmp_path, wanted), only=plan.install)
    assert installed == []
