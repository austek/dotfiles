import io
import tarfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from dotfiles_setup import antigravity as ag
from dotfiles_setup import tools
from dotfiles_setup.log import Logger

BUILD = "2.5.0-111222333"
URL = f"https://edgedl.me.gvt1.com/edgedl/release2/abc/antigravity/stable/{BUILD}/linux-x64/Antigravity%20IDE.tar.gz"
PAGE = f'<a href="{URL}">download</a>'


@pytest.fixture(autouse=True)
def isolated_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))


def tarball(*members):
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        for name in members:
            info = tarfile.TarInfo(name)
            info.size = 3
            archive.addfile(info, io.BytesIO(b"bin"))
    return buffer.getvalue()


class Machine:
    def __init__(self, fail=()):
        self.commands = []
        self.inputs = {}
        self.fail = tuple(fail)

    def __call__(self, argv, **kwargs):
        self.commands.append(list(argv))
        if kwargs.get("input") is not None:
            self.inputs[argv[2]] = kwargs["input"]
        failed = any(argv[: len(p)] == list(p) for p in self.fail)
        return SimpleNamespace(returncode=1 if failed else 0, stdout="", stderr="")

    def ran(self, *prefix):
        return any(c[: len(prefix)] == list(prefix) for c in self.commands)

    def index(self, *prefix):
        return next(i for i, c in enumerate(self.commands) if c[: len(prefix)] == list(prefix))


def make(tmp_path, machine, fetch=lambda url: PAGE, payload=None, dry_run=False):
    downloads = []
    payload = payload if payload is not None else tarball("ag/antigravity-ide", "ag/chrome-sandbox")

    def download(url, dest):
        downloads.append(url)
        dest.write_bytes(payload)

    t = tools.Tooling(Logger(dry_run=dry_run, verbosity=1), tmp_path, run=machine, fetch=fetch, download=download)
    return t, downloads, ag.Layout(root=tmp_path / "root")


def stage_files(layout):
    sandbox = layout.staging_dir / "chrome-sandbox"
    icon = layout.install_dir / "resources/app/resources/linux/code.png"
    for path in (sandbox, icon):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("")


def test_unsupported_architecture_installs_nothing(tmp_path):
    machine = Machine()
    t, downloads, layout = make(tmp_path, machine)
    assert ag.install_antigravity_ide(t, layout, machine="riscv64")
    assert downloads == [] and machine.commands == []


def test_dry_run_resolves_and_installs_nothing(tmp_path):
    def refuse(url):
        raise AssertionError(url)

    machine = Machine()
    t, downloads, layout = make(tmp_path, machine, fetch=refuse, dry_run=True)
    assert ag.install_antigravity_ide(t, layout, machine="x86_64")
    assert downloads == [] and machine.commands == []


def test_resolve_takes_the_build_from_the_download_page(tmp_path):
    t, _, _ = make(tmp_path, Machine())
    resolved = ag.resolve_build(t, "linux-x64")
    assert (resolved.version, resolved.url, resolved.cache_key) == ("2.5.0", URL, f"{BUILD}.tar.gz")


def test_resolve_falls_back_to_the_pinned_build_when_the_page_fails(tmp_path):
    def broken(url):
        raise OSError("offline")

    t, _, _ = make(tmp_path, Machine(), fetch=broken)
    resolved = ag.resolve_build(t, "linux-arm")
    assert resolved.cache_key == f"{ag.PINNED_BUILD}.tar.gz"
    assert "/linux-arm/" in resolved.url


def test_an_up_to_date_install_is_skipped(tmp_path):
    machine = Machine()
    t, downloads, layout = make(tmp_path, machine)
    layout.build_file.parent.mkdir(parents=True)
    layout.build_file.write_text(f"{BUILD}\n")
    assert ag.install_antigravity_ide(t, layout, machine="x86_64")
    assert downloads == [] and machine.commands == []


def test_a_new_build_is_staged_swapped_and_wired_up_in_order(tmp_path):
    machine = Machine()
    t, downloads, layout = make(tmp_path, machine)
    stage_files(layout)
    assert ag.install_antigravity_ide(t, layout, machine="x86_64")
    assert downloads == [URL]
    order = [
        machine.index("sudo", "mkdir", "-p", str(layout.staging_dir)),
        machine.index("sudo", "chown", "-R", "root:root", str(layout.staging_dir)),
        machine.index("sudo", "chmod", "4755", str(layout.staging_dir / "chrome-sandbox")),
        machine.index("sudo", "mv", "--", str(layout.staging_dir), str(layout.install_dir)),
        machine.index("sudo", "ln", "-sfn"),
        machine.index("sudo", "tee", str(layout.desktop)),
        machine.index("sudo", "tee", str(layout.build_file)),
    ]
    assert order == sorted(order)
    assert machine.inputs[str(layout.build_file)] == f"{BUILD}\n"
    assert f"Exec={layout.install_dir}/antigravity-ide %U" in machine.inputs[str(layout.desktop)]


def test_the_icon_is_copied_when_the_archive_ships_one(tmp_path):
    machine = Machine()
    t, _, layout = make(tmp_path, machine)
    stage_files(layout)
    ag.install_antigravity_ide(t, layout, machine="x86_64")
    assert machine.ran("sudo", "cp", "--", str(layout.install_dir / "resources/app/resources/linux/code.png"), str(layout.icon))


def test_a_missing_sandbox_only_warns(tmp_path):
    machine = Machine()
    t, _, layout = make(tmp_path, machine)
    ag.install_antigravity_ide(t, layout, machine="x86_64")
    assert not machine.ran("sudo", "chmod")
    assert machine.ran("sudo", "mv", "--", str(layout.staging_dir), str(layout.install_dir))


def test_a_failed_copy_cleans_up_staging_and_leaves_the_install_alone(tmp_path):
    machine = Machine(fail=[("sudo", "cp", "-r")])
    t, _, layout = make(tmp_path, machine)
    assert ag.install_antigravity_ide(t, layout, machine="x86_64")
    assert not machine.ran("sudo", "mv")
    assert machine.commands[-1] == ["sudo", "rm", "-rf", "--", str(layout.staging_dir)]


def test_a_failed_swap_restores_the_previous_install(tmp_path):
    machine = Machine(fail=[("sudo", "mv", "--", str(tmp_path / "root/opt/antigravity-ide.staging"))])
    t, _, layout = make(tmp_path, machine)
    layout.old_dir.mkdir(parents=True)
    assert ag.install_antigravity_ide(t, layout, machine="x86_64")
    assert machine.ran("sudo", "mv", "--", str(layout.old_dir), str(layout.install_dir))
    assert not machine.ran("sudo", "ln")


def test_a_failed_download_continues_without_installing(tmp_path):
    machine = Machine()
    t, _, layout = make(tmp_path, machine)

    def broken(url, dest):
        raise OSError("offline")

    t = tools.Tooling(t.logger, tmp_path, run=machine, fetch=lambda url: PAGE, download=broken)
    assert ag.install_antigravity_ide(t, layout, machine="x86_64")
    assert machine.commands == []


def test_an_archive_without_the_binary_installs_nothing(tmp_path):
    machine = Machine()
    t, _, layout = make(tmp_path, machine, payload=tarball("ag/readme"))
    assert ag.install_antigravity_ide(t, layout, machine="x86_64")
    assert machine.commands == []


def test_the_legacy_install_is_removed_after_a_successful_install(tmp_path):
    machine = Machine()
    t, _, layout = make(tmp_path, machine)
    layout.legacy_dir.mkdir(parents=True)
    ag.install_antigravity_ide(t, layout, machine="x86_64")
    assert machine.ran("sudo", "rm", "-rf", "--", str(layout.legacy_dir))


def test_the_legacy_install_is_kept_when_the_new_one_fails(tmp_path):
    machine = Machine(fail=[("sudo", "chown")])
    t, _, layout = make(tmp_path, machine)
    layout.legacy_dir.mkdir(parents=True)
    ag.install_antigravity_ide(t, layout, machine="x86_64")
    assert not machine.ran("sudo", "rm", "-rf", "--", str(layout.legacy_dir))


def test_the_tarball_is_cached_by_build_id(tmp_path):
    machine = Machine()
    t, downloads, layout = make(tmp_path, machine)
    ag.install_antigravity_ide(t, layout, machine="x86_64")
    cached = Path(tmp_path) / "cache/dotfiles-setup/antigravity-ide" / f"{BUILD}.tar.gz"
    assert cached.is_file() and len(downloads) == 1
