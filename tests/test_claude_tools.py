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


def test_cozempic_is_installed_through_pipx(tmp_path, on_path):
    on_path.add("pipx")
    machine = Machine()
    t, _ = make(tmp_path, machine)
    ct.configure_cozempic_cli(t)
    assert machine.ran("pipx", "install", "--quiet", "cozempic")


def test_cozempic_without_pipx_installs_nothing(tmp_path, on_path):
    machine = Machine()
    t, _ = make(tmp_path, machine)
    ct.configure_cozempic_cli(t)
    assert machine.commands == []


def test_cozempic_already_installed_is_left_alone(tmp_path, on_path):
    on_path.update({"cozempic", "pipx"})
    machine = Machine()
    t, _ = make(tmp_path, machine)
    ct.configure_cozempic_cli(t)
    assert not machine.ran("pipx")


def test_serena_is_skipped_on_homelab(tmp_path, on_path):
    on_path.add("pipx")
    machine = Machine()
    t, _ = make(tmp_path, machine)
    ct.configure_serena(t, "homelab")
    assert machine.commands == []


def test_serena_without_pipx_installs_nothing(tmp_path, on_path):
    machine = Machine()
    t, _ = make(tmp_path, machine)
    ct.configure_serena(t, "work")
    assert machine.commands == []


def test_a_failed_serena_install_stops_before_init_and_registration(tmp_path, on_path):
    on_path.update({"pipx", "claude"})
    machine = Machine({("pipx", "install"): (1, "")})
    t, _ = make(tmp_path, machine)
    ct.configure_serena(t, "work")
    assert not machine.ran("serena")
    assert not machine.ran("claude")


def test_serena_is_installed_initialised_and_registered(tmp_path, on_path):
    on_path.update({"pipx", "claude"})
    machine = Machine({("claude", "mcp", "get"): (1, "")})
    t, _ = make(tmp_path, machine)
    ct.configure_serena(t, "personal")
    assert machine.ran("pipx", "install", "--python", "3.13", "--fetch-missing-python", "serena-agent", "--pip-args=--pre")
    assert machine.ran("serena", "init")
    assert machine.ran("claude", "mcp", "add", "--scope", "user", "serena")


def test_an_initialised_and_registered_serena_is_left_alone(tmp_path, on_path):
    on_path.update({"pipx", "serena", "claude"})
    config = tmp_path / ".serena/serena_config.yml"
    config.parent.mkdir(parents=True)
    config.write_text("")
    machine = Machine({("serena", "--version"): (0, "serena 1\nextra\n")})
    t, _ = make(tmp_path, machine)
    ct.configure_serena(t, "work")
    assert not machine.ran("serena", "init")
    assert not machine.ran("claude", "mcp", "add")


def test_serena_without_the_claude_cli_skips_registration(tmp_path, on_path):
    on_path.update({"pipx", "serena"})
    machine = Machine()
    t, _ = make(tmp_path, machine)
    ct.configure_serena(t, "work")
    assert not machine.ran("claude")


def jdtls(tmp_path, text):
    path = tmp_path / ".local/share/pipx/venvs/serena-agent/lib/solidlsp/language_servers/eclipse_jdtls.py"
    path.parent.mkdir(parents=True)
    path.write_text(text)
    return path


def test_the_gradle_9_patch_is_applied_with_a_backup(tmp_path, on_path):
    on_path.update({"pipx", "serena"})
    path = jdtls(tmp_path, f"x = {ct.JDTLS_ENABLED}\n")
    t, _ = make(tmp_path, Machine())
    ct.configure_serena(t, "work")
    assert ct.JDTLS_DISABLED in path.read_text()
    assert ct.JDTLS_ENABLED in path.with_name(path.name + ".bak").read_text()


def test_an_already_patched_file_is_not_rewritten(tmp_path, on_path):
    on_path.update({"pipx", "serena"})
    path = jdtls(tmp_path, f"x = {ct.JDTLS_DISABLED}\n")
    t, _ = make(tmp_path, Machine())
    ct.configure_serena(t, "work")
    assert not path.with_name(path.name + ".bak").exists()


def test_the_patch_is_not_applied_in_a_dry_run(tmp_path, on_path):
    on_path.update({"pipx", "serena"})
    path = jdtls(tmp_path, f"x = {ct.JDTLS_ENABLED}\n")
    t, _ = make(tmp_path, Machine(), dry_run=True)
    ct.configure_serena(t, "work")
    assert ct.JDTLS_ENABLED in path.read_text()


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
    for name in ("configure_rtk_cli", "configure_cozempic_cli", "configure_caveman_proxy"):
        monkeypatch.setattr(ct, name, lambda t, name=name: order.append(name))
    monkeypatch.setattr(ct, "configure_serena", lambda t, preset: order.append(f"serena:{preset}"))
    ct.configure_claude_tools(t, "work")
    assert order == ["configure_rtk_cli", "configure_cozempic_cli", "serena:work", "configure_caveman_proxy"]
