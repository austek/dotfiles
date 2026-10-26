from types import SimpleNamespace

import pytest
from dotfiles_setup import post_apt_installers as pa
from dotfiles_setup import tools
from dotfiles_setup.log import Logger


class Machine:
    """Answers commands from a table of prefix -> (returncode, stdout); unknown commands succeed."""

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


def make(tmp_path, machine, dry_run=False, downloads=None):
    def download(url, dest):
        (downloads if downloads is not None else []).append(url)
        dest.write_text("#!/bin/sh\n")

    return tools.Tooling(Logger(dry_run=dry_run, verbosity=1), tmp_path, run=machine, download=download)


@pytest.fixture
def on_path(monkeypatch):
    present = set()
    monkeypatch.setattr("shutil.which", lambda name: f"/usr/bin/{name}" if name in present else None)
    return present


def test_auditr_is_installed_through_pipx_and_gets_packaging_injected(tmp_path, on_path):
    on_path.add("pipx")
    machine = Machine()
    assert pa.install_auditr(make(tmp_path, machine)) is None
    assert machine.ran("pipx", "install", "--quiet", "--python", "python3", f"auditr=={pa.AUDITR_VERSION}")
    assert machine.ran("pipx", "inject", "--quiet", "auditr", "packaging")


def test_auditr_without_pipx_installs_nothing(tmp_path, on_path):
    machine = Machine()
    pa.install_auditr(make(tmp_path, machine))
    assert machine.commands == []


def test_auditr_needs_python_313(tmp_path, on_path):
    on_path.add("pipx")
    machine = Machine({("python3", "-c"): (1, "")})
    pa.install_auditr(make(tmp_path, machine))
    assert not machine.ran("pipx")


def test_auditr_failed_pipx_install_does_not_inject(tmp_path, on_path):
    on_path.add("pipx")
    machine = Machine({("pipx", "install"): (1, "")})
    pa.install_auditr(make(tmp_path, machine))
    assert not machine.ran("pipx", "inject")


def test_a_broken_auditr_is_repaired_by_injecting_packaging(tmp_path, on_path):
    on_path.update({"pipx", "auditr"})
    machine = Machine({("auditr", "version"): (1, "")})
    pa.install_auditr(make(tmp_path, machine))
    assert machine.ran("pipx", "inject", "--quiet", "auditr", "packaging")
    assert not machine.ran("pipx", "install")


def test_a_working_auditr_is_left_alone(tmp_path, on_path):
    on_path.update({"pipx", "auditr"})
    machine = Machine()
    pa.install_auditr(make(tmp_path, machine))
    assert not machine.ran("pipx")


def test_a_broken_auditr_is_not_repaired_in_a_dry_run(tmp_path, on_path):
    on_path.update({"pipx", "auditr"})
    machine = Machine({("auditr", "version"): (1, "")})
    pa.install_auditr(make(tmp_path, machine, dry_run=True))
    assert not machine.ran("pipx")


def test_auditr_dry_run_installs_nothing(tmp_path, on_path):
    on_path.add("pipx")
    machine = Machine()
    pa.install_auditr(make(tmp_path, machine, dry_run=True))
    assert machine.commands == []


def test_crate_already_on_path_is_skipped(tmp_path, on_path):
    on_path.add("cargo-deny")
    machine = Machine()
    pa.install_cargo_crate(make(tmp_path, machine), "cargo-deny")
    assert machine.commands == []


def test_crate_in_local_bin_is_skipped(tmp_path, on_path):
    binary = tmp_path / ".local/bin/cargo-deny"
    binary.parent.mkdir(parents=True)
    binary.write_text("")
    binary.chmod(0o755)
    machine = Machine()
    pa.install_cargo_crate(make(tmp_path, machine), "cargo-deny")
    assert machine.commands == []


def test_crate_without_cargo_reports_and_continues(tmp_path, on_path):
    machine = Machine()
    pa.install_cargo_crate(make(tmp_path, machine), "cargo-deny")
    assert machine.commands == []


def test_crate_uses_the_system_cargo_when_it_is_new_enough(tmp_path, on_path):
    on_path.add("cargo")
    machine = Machine({("cargo", "--version"): (0, "cargo 1.90.0 (abc 2025-01-01)")})
    pa.install_cargo_crate(make(tmp_path, machine), "cargo-audit")
    assert machine.ran("/usr/bin/cargo", "install", "--locked", "--quiet", "--root", str(tmp_path / ".local"), "cargo-audit")


def test_old_system_cargo_triggers_a_minimal_rustup_toolchain(tmp_path, on_path):
    on_path.add("cargo")
    rustup_cargo = str(tmp_path / ".cargo/bin/cargo")
    versions = iter([(0, "cargo 1.75.0"), (0, "cargo 1.75.0"), (0, "cargo 1.91.0")])

    class Rust(Machine):
        def __call__(self, argv, **kwargs):
            if argv[1:] == ["--version"]:
                code, out = next(versions)
                self.commands.append(list(argv))
                self.envs.append(kwargs.get("env"))
                return SimpleNamespace(returncode=code, stdout=out, stderr="")
            return super().__call__(argv, **kwargs)

    machine = Rust()
    downloads = []
    pa.install_cargo_crate(make(tmp_path, machine, downloads=downloads), "cargo-deny")
    assert downloads == [pa.RUSTUP_INIT_URL]
    assert machine.ran("sh")
    install = next(i for i, c in enumerate(machine.commands) if c[:2] == [rustup_cargo, "install"])
    assert machine.envs[install]["RUSTUP_TOOLCHAIN"] == "stable"
    assert machine.envs[install]["PATH"].startswith(str(tmp_path / ".cargo/bin"))


def test_an_existing_rustup_is_updated_rather_than_reinstalled(tmp_path, on_path):
    on_path.add("cargo")
    rustup = tmp_path / ".cargo/bin/rustup"
    rustup.parent.mkdir(parents=True)
    rustup.write_text("")
    rustup.chmod(0o755)
    versions = iter(["cargo 1.75.0", "cargo 1.75.0", "cargo 1.91.0"])

    class Rust(Machine):
        def __call__(self, argv, **kwargs):
            if argv[1:] == ["--version"]:
                self.commands.append(list(argv))
                self.envs.append(kwargs.get("env"))
                return SimpleNamespace(returncode=0, stdout=next(versions), stderr="")
            return super().__call__(argv, **kwargs)

    machine = Rust()
    pa.install_cargo_crate(make(tmp_path, machine), "cargo-deny")
    assert machine.ran(str(rustup), "update", "stable", "--no-self-update")


def test_crate_with_no_usable_cargo_installs_nothing(tmp_path, on_path):
    on_path.add("cargo")
    machine = Machine({("cargo", "--version"): (0, "cargo 1.75.0")})
    pa.install_cargo_crate(make(tmp_path, machine, downloads=[]), "cargo-deny")
    assert not machine.ran("/usr/bin/cargo", "install")


def test_crate_dry_run_installs_nothing(tmp_path, on_path):
    on_path.add("cargo")
    machine = Machine()
    pa.install_cargo_crate(make(tmp_path, machine, dry_run=True), "cargo-deny")
    assert machine.commands == []


def test_ruff_runs_after_the_apt_step_that_provides_pipx():
    assert [name for name, _ in pa.POST_APT_INSTALLERS] == ["ruff", "auditr", "cargo-deny", "cargo-audit"]


def test_post_apt_tools_run_only_for_selected_packages(tmp_path, on_path):
    on_path.add("pipx")
    machine = Machine()
    assert tools.install_post_apt_tools(make(tmp_path, machine), {"auditr"})
    assert machine.ran("pipx", "install")
    assert not machine.ran("/usr/bin/cargo")
