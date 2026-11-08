import hashlib
import io
import tarfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from dotfiles_setup import antigravity as ag
from dotfiles_setup import checksums, tools
from dotfiles_setup.log import Logger

BUILD = ag.PINNED_BUILD
URL = ag.resolve_build("linux-x64").url


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


def make(tmp_path, machine, payload=None, dry_run=False):
    downloads = []
    payload = payload if payload is not None else tarball("ag/antigravity-ide", "ag/chrome-sandbox")

    def download(url, dest):
        downloads.append(url)
        dest.write_bytes(payload)

    t = tools.Tooling(Logger(dry_run=dry_run, verbosity=1), tmp_path, run=machine, download=download)
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
    assert downloads == []
    assert machine.commands == []


def test_dry_run_downloads_and_installs_nothing(tmp_path):
    machine = Machine()
    t, downloads, layout = make(tmp_path, machine, dry_run=True)
    assert ag.install_antigravity_ide(t, layout, machine="x86_64")
    assert downloads == []
    assert machine.commands == []


def test_resolve_uses_the_pinned_build():
    resolved = ag.resolve_build("linux-x64")
    assert (resolved.version, resolved.url, resolved.cache_key) == (BUILD.split("-")[0], URL, f"{BUILD}.tar.gz")


@pytest.mark.parametrize("arch", ["aarch64", "arm64"])
def test_arm_installs_nothing(tmp_path, arch, capsys):
    machine = Machine()
    t, downloads, layout = make(tmp_path, machine)
    assert ag.install_antigravity_ide(t, layout, machine=arch)
    assert downloads == [] and machine.commands == []
    captured = capsys.readouterr()
    assert "x86_64 only" in captured.out and captured.err == ""


def test_a_digest_mismatch_installs_nothing(tmp_path):
    machine = Machine()
    t, _, layout = make(tmp_path, machine)
    t = tools.Tooling(t.logger, tmp_path, run=machine, download=t.download, checksums={URL: "0" * 64})
    assert ag.install_antigravity_ide(t, layout, machine="x86_64")
    assert not machine.ran("sudo", "cp")


def digest_of(payload):
    return hashlib.sha256(payload).hexdigest()


def cached_tarball(tmp_path):
    return tmp_path / "cache/dotfiles-setup/antigravity-ide" / f"{BUILD}.tar.gz"


def test_a_matching_digest_installs(tmp_path):
    machine = Machine()
    payload = tarball("ag/antigravity-ide", "ag/chrome-sandbox")
    t, _, layout = make(tmp_path, machine, payload=payload)
    t = tools.Tooling(t.logger, tmp_path, run=machine, download=t.download, checksums={URL: digest_of(payload)})
    assert ag.install_antigravity_ide(t, layout, machine="x86_64")
    assert machine.ran("sudo", "cp")


def test_an_unlisted_url_installs_nothing_and_says_why(tmp_path, capsys):
    machine = Machine()
    t, _, layout = make(tmp_path, machine)
    t = tools.Tooling(t.logger, tmp_path, run=machine, download=t.download, checksums={})
    assert ag.install_antigravity_ide(t, layout, machine="x86_64")
    assert not machine.ran("sudo", "cp")
    assert "Refusing Antigravity IDE download: no digest recorded" in capsys.readouterr().err


def test_a_rejected_download_is_never_cached(tmp_path):
    machine = Machine()
    t, _, layout = make(tmp_path, machine)
    t = tools.Tooling(t.logger, tmp_path, run=machine, download=t.download, checksums={URL: "0" * 64})
    ag.install_antigravity_ide(t, layout, machine="x86_64")
    assert not cached_tarball(tmp_path).exists()


def test_a_tampered_cached_tarball_is_replaced_by_a_verified_download(tmp_path):
    payload = tarball("ag/antigravity-ide", "ag/chrome-sandbox")
    cached = cached_tarball(tmp_path)
    cached.parent.mkdir(parents=True)
    cached.write_bytes(b"tampered")
    machine = Machine()
    t, _, layout = make(tmp_path, machine, payload=payload)
    t = tools.Tooling(t.logger, tmp_path, run=machine, download=t.download, checksums={URL: digest_of(payload)})
    ag.install_antigravity_ide(t, layout, machine="x86_64")
    assert cached.read_bytes() == payload


def test_the_pinned_url_has_a_shipped_digest():
    table = checksums.load(Path(__file__).parent.parent / "packages" / checksums.FILE_NAME)
    assert URL in table


def test_an_up_to_date_install_is_skipped(tmp_path):
    machine = Machine()
    t, downloads, layout = make(tmp_path, machine)
    layout.build_file.parent.mkdir(parents=True)
    layout.build_file.write_text(f"{BUILD}\n")
    assert ag.install_antigravity_ide(t, layout, machine="x86_64")
    assert downloads == []
    assert machine.commands == []


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


def test_the_previous_install_is_deleted_only_after_the_new_one_is_wired_up(tmp_path):
    machine = Machine()
    t, _, layout = make(tmp_path, machine)
    stage_files(layout)
    ag.install_antigravity_ide(t, layout, machine="x86_64")
    last_rm = max(i for i, c in enumerate(machine.commands) if c[:5] == ["sudo", "rm", "-rf", "--", str(layout.old_dir)])
    assert last_rm > machine.index("sudo", "tee", str(layout.build_file))


def test_a_wiring_failure_restores_the_previous_install(tmp_path):
    machine = Machine(fail=[("sudo", "tee", str(tmp_path / "root/usr/share/applications/antigravity-ide.desktop"))])
    t, _, layout = make(tmp_path, machine)
    layout.old_dir.mkdir(parents=True)
    assert ag.install_antigravity_ide(t, layout, machine="x86_64")
    assert machine.ran("sudo", "mv", "--", str(layout.old_dir), str(layout.install_dir))
    assert not any(
        c[:5] == ["sudo", "rm", "-rf", "--", str(layout.old_dir)] and i > machine.index("sudo", "tee", str(layout.desktop))
        for i, c in enumerate(machine.commands)
    )
    assert not machine.ran("sudo", "tee", str(layout.build_file))


def test_a_failed_download_continues_without_installing(tmp_path):
    machine = Machine()
    t, _, layout = make(tmp_path, machine)

    def broken(url, dest):
        raise OSError("offline")

    t = tools.Tooling(t.logger, tmp_path, run=machine, download=broken)
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
    assert cached.is_file()
    assert len(downloads) == 1
