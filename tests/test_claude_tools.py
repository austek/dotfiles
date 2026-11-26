import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from dotfiles_setup import claude_tools as ct
from dotfiles_setup import tools
from dotfiles_setup.log import Logger


class Machine:
    def __init__(self, answers=None):
        self.commands = []
        self.envs = []
        self.answers = answers or {}

    def __call__(self, argv, **kwargs):
        self.commands.append(list(argv))
        self.envs.append(kwargs.get("env"))
        for prefix, (code, out) in self.answers.items():
            if argv[: len(prefix)] == list(prefix):
                return SimpleNamespace(returncode=code, stdout=out, stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    def ran(self, *prefix):
        return any(c[: len(prefix)] == list(prefix) for c in self.commands)


@pytest.fixture
def on_path(monkeypatch):
    present = set()
    monkeypatch.setattr("shutil.which", lambda name, path=None: f"/usr/bin/{name}" if name in present else None)
    return present


def make(tmp_path, machine, dry_run=False):
    downloads = []

    def download(url, dest):
        downloads.append(url)
        dest.write_text("#!/bin/sh\n")

    t = tools.Tooling(Logger(dry_run=dry_run, verbosity=1), tmp_path, run=machine, download=download)
    return t, downloads


def test_rtk_already_installed_is_left_alone(tmp_path, on_path):
    on_path.add("rtk")
    t, downloads = make(tmp_path, Machine({("rtk", "--version"): (0, "rtk 1.0\n")}))
    ct.configure_rtk_cli(t)
    assert downloads == []


def test_rtk_is_installed_through_its_script(tmp_path, on_path):
    machine = Machine()
    t, downloads = make(tmp_path, machine)
    ct.configure_rtk_cli(t)
    assert downloads == [ct.RTK_INSTALL_URL]
    assert machine.commands[0][0] == "sh"


def test_rtk_dry_run_downloads_nothing(tmp_path, on_path):
    t, downloads = make(tmp_path, Machine(), dry_run=True)
    ct.configure_rtk_cli(t)
    assert downloads == []


def test_dfctl_no_longer_installs_or_configures_cozempic():
    assert not hasattr(ct, "configure_cozempic_cli")
    assert not hasattr(ct, "_report_cozempic")
    assert not hasattr(ct, "_tool_env")


def test_the_base_settings_carry_no_cozempic_entries():
    settings = json.loads((Path(__file__).resolve().parent.parent / "claude/.claude/settings.json").read_text())
    assert [key for key in settings.get("env", {}) if key.startswith("COZEMPIC_")] == []
    assert "cozempic@cozempic" not in settings["enabledPlugins"]
    assert "cozempic" not in settings["extraKnownMarketplaces"]


def test_version_checks_run_with_the_inherited_environment(tmp_path, on_path):
    on_path.add("rtk")
    machine = Machine()
    t, _ = make(tmp_path, machine)
    ct._version_of(t, "rtk")
    assert machine.envs == [None]


def make_nvm_node(tmp_path, *versions):
    for version in versions:
        (tmp_path / ".nvm/versions/node" / version / "bin").mkdir(parents=True)


def test_caveman_without_npm_is_skipped(tmp_path, on_path):
    machine = Machine()
    t, _ = make(tmp_path, machine)
    ct.configure_caveman_proxy(t)
    assert machine.commands == []


def test_the_newest_nvm_node_is_put_on_path_for_npm(tmp_path, on_path):
    make_nvm_node(tmp_path, "v9.11.2", "v22.4.0", "v20.18.1")
    t, _ = make(tmp_path, Machine())
    assert ct._node_env(t)["PATH"].startswith(str(tmp_path / ".nvm/versions/node/v22.4.0/bin"))


def test_caveman_is_installed_and_gets_its_engine(tmp_path, monkeypatch):
    make_nvm_node(tmp_path, "v22.4.0")
    seen = {}

    def which(name, path=None):
        seen[name] = path
        return f"/n/{name}" if name == "npm" or (name == "caveman" and "installed" in seen) else None

    monkeypatch.setattr("shutil.which", which)
    machine = Machine({("/n/caveman", "status"): (0, "caveman-proxy not installed")})

    class Installing(Machine):
        def __call__(self, argv, **kwargs):
            if argv[:2] == ["npm", "install"]:
                seen["installed"] = True
            return machine(argv, **kwargs)

    t, _ = make(tmp_path, Installing())
    ct.configure_caveman_proxy(t)
    assert machine.ran("npm", "install", "-g", "--ignore-scripts", "@caveman-ai/cli")
    assert machine.ran("/n/caveman", "setup", "--install")
    install = next(i for i, c in enumerate(machine.commands) if c[:2] == ["npm", "install"])
    assert str(tmp_path / ".nvm/versions/node/v22.4.0/bin") in machine.envs[install]["PATH"]


def test_a_current_caveman_install_is_left_alone(tmp_path, on_path):
    on_path.update({"npm", "caveman"})
    machine = Machine({("caveman", "version"): (0, '{"version": "1.2.3"}'), ("/usr/bin/caveman", "status"): (0, "ok")})
    t, _ = make(tmp_path, machine)
    ct.configure_caveman_proxy(t)
    assert not machine.ran("npm")
    assert not machine.ran("/usr/bin/caveman", "setup")


def test_a_failed_caveman_npm_install_stops(tmp_path, on_path):
    on_path.add("npm")
    machine = Machine({("npm", "install"): (1, "")})
    t, _ = make(tmp_path, machine)
    ct.configure_caveman_proxy(t)
    assert not machine.ran("caveman")


def test_the_claude_tools_run_in_order(tmp_path, monkeypatch):
    order = []
    t, _ = make(tmp_path, Machine())
    for name in ("configure_rtk_cli", "configure_caveman_proxy"):
        monkeypatch.setattr(ct, name, lambda t, name=name: order.append(name))
    ct.configure_claude_tools(t)
    assert order == ["configure_rtk_cli", "configure_caveman_proxy"]
