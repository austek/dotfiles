from types import SimpleNamespace

import pytest
from dotfiles_setup import tools
from dotfiles_setup import vendor_installers as vi
from dotfiles_setup.log import Logger


@pytest.fixture(autouse=True)
def nothing_on_path(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: None)


class Machine:
    def __init__(self, fail=(), stdout=""):
        self.commands = []
        self.fail = tuple(fail)
        self.stdout = stdout

    def __call__(self, argv, **kwargs):
        self.commands.append(list(argv))
        failed = any(argv[: len(p)] == list(p) for p in self.fail)
        return SimpleNamespace(returncode=1 if failed else 0, stdout=self.stdout, stderr="")

    def ran(self, *prefix):
        return any(c[: len(prefix)] == list(prefix) for c in self.commands)


def make(tmp_path, machine, dry_run=False, broken_download=False):
    downloads = []

    def download(url, dest):
        downloads.append(url)
        if broken_download:
            raise OSError("offline")
        dest.write_text("#!/bin/sh\n")

    t = tools.Tooling(Logger(dry_run=dry_run, verbosity=1), tmp_path, run=machine, download=download)
    return t, downloads


def test_vendor_script_is_downloaded_then_run_with_its_shell(tmp_path):
    machine = Machine()
    t, downloads = make(tmp_path, machine)
    assert vi.install_vendor(t, vi.UV) is None
    assert downloads == ["https://astral.sh/uv/install.sh"]
    assert machine.commands[0][0] == "sh"


def test_vendor_script_that_fails_never_aborts_setup(tmp_path):
    t, _ = make(tmp_path, Machine(fail=[("sh",)]))
    assert vi.install_vendor(t, vi.UV) is None


def test_truncated_or_failed_download_never_runs_the_script(tmp_path):
    machine = Machine()
    t, _ = make(tmp_path, machine, broken_download=True)
    assert vi.install_vendor(t, vi.UV) is None
    assert machine.commands == []


def test_dry_run_downloads_nothing(tmp_path):
    machine = Machine()
    t, downloads = make(tmp_path, machine, dry_run=True)
    assert vi.install_vendor(t, vi.CODERABBIT) is None
    assert downloads == []
    assert machine.commands == []


def test_uv_found_at_its_default_location_is_skipped(tmp_path):
    binary = tmp_path / ".local/bin/uv"
    binary.parent.mkdir(parents=True)
    binary.write_text("")
    binary.chmod(0o755)
    t, downloads = make(tmp_path, Machine())
    assert vi.install_vendor(t, vi.UV) is None
    assert downloads == []


def test_sonarqube_cli_runs_with_bash(tmp_path):
    machine = Machine()
    t, _ = make(tmp_path, machine)
    vi.install_vendor(t, vi.SONARQUBE_CLI)
    assert machine.commands[0][0] == "bash"


def test_coderabbit_reports_its_version(tmp_path, monkeypatch, capsys):
    binary = str(tmp_path / "bin" / "coderabbit")
    lookups = iter([None, binary])
    monkeypatch.setattr("shutil.which", lambda name: next(lookups))
    machine = Machine(stdout="coderabbit 1.2.3\n")
    t, _ = make(tmp_path, machine)
    vi.install_vendor(t, vi.CODERABBIT)
    assert "CodeRabbit CLI installed (coderabbit 1.2.3)." in capsys.readouterr().out
    assert machine.ran(binary, "--version")


def test_coderabbit_off_path_after_install_does_not_crash(tmp_path, capsys):
    machine = Machine()
    t, _ = make(tmp_path, machine)
    assert vi.install_vendor(t, vi.CODERABBIT) is None
    assert "restart your shell to put it on PATH" in capsys.readouterr().out
    assert not machine.ran("coderabbit")


def test_ruff_installs_through_pipx(tmp_path, monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/pipx" if name == "pipx" else None)
    machine = Machine()
    t, _ = make(tmp_path, machine)
    assert vi.install_ruff(t) is None
    assert machine.ran("pipx", "install", "--quiet", "ruff")


def test_ruff_without_pipx_reports_and_continues(tmp_path):
    machine = Machine()
    t, _ = make(tmp_path, machine)
    assert vi.install_ruff(t) is None
    assert machine.commands == []


def test_ruff_already_installed_is_skipped(tmp_path, monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/ruff" if name == "ruff" else None)
    machine = Machine()
    t, _ = make(tmp_path, machine)
    assert vi.install_ruff(t) is None
    assert machine.commands == []
