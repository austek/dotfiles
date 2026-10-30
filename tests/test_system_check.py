from types import SimpleNamespace

import pytest
from dotfiles_setup import system_check as sc
from dotfiles_setup import tools
from dotfiles_setup.log import Logger
from dotfiles_setup.rollback import RollbackLog
from dotfiles_setup.system_steps import SystemContext


class Machine:
    def __init__(self, installed=(), docker_ok=True, debs=""):
        self.installed = installed
        self.docker_ok = docker_ok
        self.debs = debs

    def __call__(self, argv, **kwargs):
        if argv[0] == "dpkg-query":
            out = "".join(f"ii  {name}\n" for name in self.installed)
        elif argv[0] == "dpkg":
            out = self.debs
        elif argv[:2] == ["getent", "group"]:
            return SimpleNamespace(returncode=0 if self.docker_ok else 2, stdout="", stderr="")
        elif argv[0] == "groups":
            out = "user : user docker" if self.docker_ok else "user : user"
        else:
            out = ""
        return SimpleNamespace(returncode=0, stdout=out, stderr="")


def login_shell(monkeypatch, shell):
    monkeypatch.setattr("pwd.getpwuid", lambda uid: SimpleNamespace(pw_shell=shell))


@pytest.fixture(autouse=True)
def zsh_login_shell(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name, path=None: "/usr/bin/zsh" if name == "zsh" else None)
    login_shell(monkeypatch, "/usr/bin/zsh")


def make(tmp_path, machine, packages=("vim", "git")):
    t = tools.Tooling(Logger(dry_run=False, verbosity=1), tmp_path, run=machine)
    (tmp_path / "repo" / "packages").mkdir(parents=True, exist_ok=True)
    return SystemContext(t, tmp_path / "repo", frozenset(packages), RollbackLog(tmp_path / "log"))


@pytest.fixture
def nosnap(tmp_path):
    path = tmp_path / "nosnap.pref"
    path.write_text("Package: snapd\n")
    return path


def test_a_converged_machine_has_nothing_to_do(tmp_path, nosnap):
    assert sc.system_stage_reasons(make(tmp_path, Machine(installed=("vim", "git"))), nosnap) == []


def test_a_missing_apt_package_is_a_reason(tmp_path, nosnap):
    found = sc.system_stage_reasons(make(tmp_path, Machine(installed=("vim",))), nosnap)
    assert found == ["1 apt package(s) not installed (git...)"]


def test_packages_installed_outside_apt_are_not_checked_against_dpkg(tmp_path, nosnap):
    ctx = make(tmp_path, Machine(installed=("vim",)), packages=("vim", "nvm", "uv", "ruff"))
    assert sc.system_stage_reasons(ctx, nosnap) == []


def test_an_installed_snapd_is_a_reason(tmp_path, nosnap):
    found = sc.system_stage_reasons(make(tmp_path, Machine(installed=("vim", "git", "snapd"))), nosnap)
    assert found == ["snapd is installed"]


def test_a_missing_snapd_block_is_a_reason(tmp_path):
    found = sc.system_stage_reasons(make(tmp_path, Machine(installed=("vim", "git"))), tmp_path / "absent.pref")
    assert found == ["the snapd block preference is missing"]


def test_an_unset_up_docker_group_is_a_reason_only_when_docker_is_selected(tmp_path, nosnap):
    machine = Machine(installed=("vim", "docker-ce"), docker_ok=False)
    assert sc.system_stage_reasons(make(tmp_path, machine, packages=("vim",)), nosnap) == []
    found = sc.system_stage_reasons(make(tmp_path, machine, packages=("vim", "docker-ce")), nosnap)
    assert found == ["the docker group is not set up"]


def test_a_login_shell_other_than_zsh_is_a_reason(tmp_path, nosnap, monkeypatch):
    login_shell(monkeypatch, "/bin/bash")
    found = sc.system_stage_reasons(make(tmp_path, Machine(installed=("vim", "git"))), nosnap)
    assert found == ["the login shell is not zsh"]


def test_a_shell_changed_in_passwd_counts_before_the_next_login(tmp_path, nosnap, monkeypatch):
    monkeypatch.setenv("SHELL", "/bin/bash")
    assert sc.system_stage_reasons(make(tmp_path, Machine(installed=("vim", "git"))), nosnap) == []


def test_a_github_deb_that_is_not_installed_is_a_reason(tmp_path, nosnap):
    ctx = make(tmp_path, Machine(installed=("vim", "git")))
    (ctx.dotfiles_dir / "packages" / "github_bins.txt").write_text("derailed/k9s 0.51.0 k9s_linux_amd64.deb\n")
    assert sc.system_stage_reasons(ctx, nosnap) == ["1 GitHub .deb package(s) not installed"]
    ctx = make(tmp_path / "ok", Machine(installed=("vim", "git"), debs="ii  k9s  0.51.0 amd64 x\n"))
    (ctx.dotfiles_dir / "packages" / "github_bins.txt").write_text("derailed/k9s 0.51.0 k9s_linux_amd64.deb\n")
    assert sc.system_stage_reasons(ctx, nosnap) == []
