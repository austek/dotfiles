from types import SimpleNamespace

import pytest
from dotfiles_setup import apt_packages as ap
from dotfiles_setup import system_steps as ss
from dotfiles_setup import tools
from dotfiles_setup.log import Logger
from dotfiles_setup.rollback import RollbackLog


class Machine:
    def __init__(self, failing=(), dpkg=""):
        self.commands = []
        self.failing = tuple(failing)
        self.dpkg = dpkg

    def __call__(self, argv, **kwargs):
        self.commands.append(list(argv))
        failed = any(argv[: len(p)] == list(p) for p in self.failing)
        out = self.dpkg if argv[:2] == ["dpkg", "-l"] else ""
        return SimpleNamespace(returncode=1 if failed else 0, stdout=out, stderr="")

    def ran(self, *prefix):
        return any(c[: len(prefix)] == list(prefix) for c in self.commands)


@pytest.fixture(autouse=True)
def isolated_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))


def make(tmp_path, machine, packages=(), dry_run=False, downloads=None):
    def download(url, dest):
        (downloads if downloads is not None else []).append(url)
        dest.write_bytes(b"deb")

    t = tools.Tooling(Logger(dry_run=dry_run, verbosity=1), tmp_path, run=machine, download=download)
    repo = tmp_path / "repo"
    (repo / "packages").mkdir(parents=True, exist_ok=True)
    return ss.SystemContext(t, repo, frozenset(packages), RollbackLog(tmp_path / "rollback.log"))


def test_only_apt_packages_are_installed_and_custom_ones_are_left_to_their_installers(tmp_path):
    machine = Machine()
    ctx = make(tmp_path, machine, packages=["vim", "git", "nvm", "uv", "cargo-deny", "antigravity-ide"])
    assert ap.install_packages(ctx, tmp_path / "sources")
    assert machine.commands == [
        ["sudo", "apt-get", "update"],
        ["sudo", "DEBIAN_FRONTEND=noninteractive", "apt-get", "install", "-y", "git", "vim"],
    ]


def test_no_apt_packages_means_no_apt_calls(tmp_path):
    machine = Machine()
    assert ap.install_packages(make(tmp_path, machine, packages=["nvm"]), tmp_path / "sources")
    assert machine.commands == []


def test_a_failed_apt_update_stops_the_run(tmp_path):
    machine = Machine(failing=[("sudo", "apt-get", "update")])
    assert not ap.install_packages(make(tmp_path, machine, packages=["vim"]), tmp_path / "sources")
    assert len(machine.commands) == 1


def test_a_failed_apt_install_stops_the_run(tmp_path):
    machine = Machine(failing=[("sudo", "DEBIAN_FRONTEND=noninteractive")])
    assert not ap.install_packages(make(tmp_path, machine, packages=["vim"]), tmp_path / "sources")


def test_the_install_is_a_dry_run_notice_only(tmp_path):
    machine = Machine()
    assert ap.install_packages(make(tmp_path, machine, packages=["vim"], dry_run=True), tmp_path / "sources")
    assert machine.commands == []


def test_a_legacy_list_next_to_a_managed_source_is_removed(tmp_path):
    sources = tmp_path / "sources"
    sources.mkdir()
    (sources / "docker.sources").write_text("")
    (sources / "docker.list").write_text("")
    (sources / "other.list").write_text("")
    machine = Machine()
    ap.install_packages(make(tmp_path, machine, packages=["vim"]), sources)
    assert machine.ran("sudo", "rm", "-f", str(sources / "docker.list"))
    assert not machine.ran("sudo", "rm", "-f", str(sources / "other.list"))


def write_bins(ctx, text):
    (ctx.dotfiles_dir / "packages" / "github_bins.txt").write_text(text)


def test_a_missing_or_empty_bin_list_is_skipped(tmp_path):
    machine = Machine()
    ctx = make(tmp_path, machine)
    assert ap.install_github_bins(ctx) is None
    write_bins(ctx, "")
    assert ap.install_github_bins(ctx) is None
    assert machine.commands == []


def test_each_listed_deb_is_downloaded_from_its_release_and_installed(tmp_path):
    machine = Machine()
    downloads = []
    ctx = make(tmp_path, machine, downloads=downloads)
    write_bins(ctx, "# comment\n\nowner/tool 1.2.3 tool_1.2.3_amd64.deb\n")
    ap.install_github_bins(ctx)
    assert downloads == ["https://github.com/owner/tool/releases/download/v1.2.3/tool_1.2.3_amd64.deb"]
    assert any(c[:3] == ["sudo", "dpkg", "-i"] and c[3].endswith("tool_1.2.3_amd64.deb") for c in machine.commands)


def test_an_installed_package_is_skipped(tmp_path):
    machine = Machine(dpkg="ii  tool  1.2.3  amd64  A tool\n")
    downloads = []
    ctx = make(tmp_path, machine, downloads=downloads)
    write_bins(ctx, "owner/tool 1.2.3 tool_1.2.3_amd64.deb\n")
    ap.install_github_bins(ctx)
    assert downloads == []


def test_a_package_whose_name_only_starts_the_same_is_not_mistaken_for_installed(tmp_path):
    machine = Machine(dpkg="ii  toolbox  1  amd64  Other\n")
    downloads = []
    ctx = make(tmp_path, machine, downloads=downloads)
    write_bins(ctx, "owner/tool 1.2.3 tool_1.2.3_amd64.deb\n")
    ap.install_github_bins(ctx)
    assert len(downloads) == 1


def test_a_failed_dpkg_install_runs_apt_fix_broken(tmp_path):
    machine = Machine(failing=[("sudo", "dpkg")])
    ctx = make(tmp_path, machine)
    write_bins(ctx, "owner/tool 1.2.3 tool_1.2.3_amd64.deb\n")
    ap.install_github_bins(ctx)
    assert machine.ran("sudo", "apt-get", "-y", "--fix-broken", "install")


def test_a_malformed_line_is_reported_and_the_rest_still_install(tmp_path):
    machine = Machine()
    downloads = []
    ctx = make(tmp_path, machine, downloads=downloads)
    write_bins(ctx, "owner/only-two-fields 1.0\nowner/tool 1.2.3 tool_1.2.3_amd64.deb\n")
    ap.install_github_bins(ctx)
    assert len(downloads) == 1


def test_a_failed_download_is_reported_and_nothing_is_installed(tmp_path):
    machine = Machine()
    ctx = make(tmp_path, machine)

    def broken(url, dest):
        raise OSError("offline")

    broken_ctx = ss.SystemContext(
        tools.Tooling(ctx.t.logger, tmp_path, run=machine, download=broken), ctx.dotfiles_dir, ctx.packages, ctx.changes,
    )
    write_bins(ctx, "owner/tool 1.2.3 tool_1.2.3_amd64.deb\n")
    ap.install_github_bins(broken_ctx)
    assert not machine.ran("sudo", "dpkg")


def test_bins_are_a_dry_run_notice_only(tmp_path):
    machine = Machine()
    downloads = []
    ctx = make(tmp_path, machine, dry_run=True, downloads=downloads)
    write_bins(ctx, "owner/tool 1.2.3 tool_1.2.3_amd64.deb\n")
    ap.install_github_bins(ctx)
    assert downloads == []
    assert machine.commands == []


def test_a_downloaded_deb_is_cached_by_version_and_filename(tmp_path):
    ctx = make(tmp_path, Machine())
    write_bins(ctx, "owner/tool 1.2.3 tool_1.2.3_amd64.deb\n")
    ap.install_github_bins(ctx)
    assert (tmp_path / "cache/dotfiles-setup/github-bins/owner/tool/1.2.3-tool_1.2.3_amd64.deb").is_file()
