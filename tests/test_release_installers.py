import io
import tarfile
import zipfile
from types import SimpleNamespace

import pytest
from dotfiles_setup import release_installers as ri
from dotfiles_setup import tools
from dotfiles_setup.log import Logger

LAZYDOCKER_TAG = '{"tag_name": "v1.2.3"}'


@pytest.fixture(autouse=True)
def isolated_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.setattr("shutil.which", lambda name: None)


def tarball(member):
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        info = tarfile.TarInfo(member)
        info.size = 3
        archive.addfile(info, io.BytesIO(b"bin"))
    return buffer.getvalue()


class Machine:
    """Records every command and answers dpkg -l from configurable state."""

    def __init__(self, dpkg_listing="", fail=()):
        self.commands = []
        self.dpkg_listing = dpkg_listing
        self.fail = tuple(fail)

    def __call__(self, argv, **kwargs):
        self.commands.append(list(argv))
        if argv[:2] == ["dpkg", "-l"]:
            return SimpleNamespace(returncode=0, stdout=self.dpkg_listing, stderr="")
        failed = any(argv[: len(prefix)] == list(prefix) for prefix in self.fail)
        return SimpleNamespace(returncode=1 if failed else 0, stdout="", stderr="")

    def ran(self, *prefix):
        return any(command[: len(prefix)] == list(prefix) for command in self.commands)


def make(tmp_path, machine, fetch=lambda url: "", payload=b"x", dry_run=False, redirect=lambda url: None):
    downloads = []

    def download(url, dest):
        downloads.append(url)
        if payload is None:
            raise OSError("offline")
        dest.write_bytes(payload)

    t = tools.Tooling(
        Logger(dry_run=dry_run, verbosity=1), tmp_path, run=machine, fetch=fetch, download=download, redirect=redirect,
    )
    return t, downloads


def test_installed_tool_is_skipped(tmp_path, monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/lazydocker")
    t, downloads = make(tmp_path, Machine())
    assert ri.install_release(t, ri.LAZYDOCKER)
    assert downloads == []


def test_dry_run_resolves_and_downloads_nothing(tmp_path):
    def refuse(url):
        raise AssertionError(url)

    t, downloads = make(tmp_path, Machine(), fetch=refuse, dry_run=True)
    assert ri.install_release(t, ri.LAZYDOCKER)
    assert downloads == []


def test_lazydocker_resolve_failure_downloads_nothing(tmp_path):
    t, downloads = make(tmp_path, Machine(), fetch=lambda url: "{}")
    assert ri.install_release(t, ri.LAZYDOCKER)
    assert downloads == []


def test_lazydocker_download_failure_continues(tmp_path):
    machine = Machine()
    t, _ = make(tmp_path, machine, fetch=lambda url: LAZYDOCKER_TAG, payload=None)
    assert ri.install_release(t, ri.LAZYDOCKER)
    assert not machine.ran("sudo", "install")


def test_lazydocker_bad_archive_continues_without_installing(tmp_path):
    machine = Machine()
    t, _ = make(tmp_path, machine, fetch=lambda url: LAZYDOCKER_TAG, payload=b"not a tarball")
    assert ri.install_release(t, ri.LAZYDOCKER)
    assert not machine.ran("sudo", "install")


def test_lazydocker_installs_the_extracted_binary(tmp_path):
    machine = Machine()
    t, downloads = make(tmp_path, machine, fetch=lambda url: LAZYDOCKER_TAG, payload=tarball("lazydocker"))
    assert ri.install_release(t, ri.LAZYDOCKER)
    assert downloads == ["https://github.com/jesseduffield/lazydocker/releases/latest/download/lazydocker_1.2.3_Linux_x86_64.tar.gz"]
    install = next(c for c in machine.commands if c[:2] == ["sudo", "install"])
    assert install[2].endswith("/lazydocker")
    assert install[3] == "/usr/local/bin"


def test_lazydocker_install_failure_continues(tmp_path):
    machine = Machine(fail=[("sudo", "install")])
    t, _ = make(tmp_path, machine, fetch=lambda url: LAZYDOCKER_TAG, payload=tarball("lazydocker"))
    assert ri.install_release(t, ri.LAZYDOCKER)


def test_second_run_uses_the_cached_download(tmp_path):
    first, downloads = make(tmp_path, Machine(), fetch=lambda url: LAZYDOCKER_TAG, payload=tarball("lazydocker"))
    ri.install_release(first, ri.LAZYDOCKER)
    second, more = make(tmp_path, Machine(), fetch=lambda url: LAZYDOCKER_TAG, payload=None)
    ri.install_release(second, ri.LAZYDOCKER)
    assert len(downloads) == 1
    assert more == []


def test_cache_drops_entries_for_other_versions(tmp_path):
    cache = tmp_path / "cache" / "dotfiles-setup" / "lazydocker"
    cache.mkdir(parents=True)
    (cache / "0.9.9.tar.gz").write_bytes(b"old")
    t, _ = make(tmp_path, Machine(), fetch=lambda url: LAZYDOCKER_TAG, payload=tarball("lazydocker"))
    ri.install_release(t, ri.LAZYDOCKER)
    assert sorted(p.name for p in cache.iterdir()) == ["1.2.3.tar.gz"]


def test_zoom_takes_its_version_from_the_redirect(tmp_path):
    t, downloads = make(tmp_path, Machine(), redirect=lambda url: "https://cdn.zoom.us/prod/6.1.2.3/zoom_amd64.deb")
    assert ri.install_release(t, ri.ZOOM)
    assert downloads == [ri.ZOOM_URL]
    assert (tmp_path / "cache/dotfiles-setup/Zoom/zoom_amd64-6.1.2.3.deb").is_file()


def test_zoom_without_a_redirect_is_versioned_latest(tmp_path):
    t, _ = make(tmp_path, Machine())
    assert ri.install_release(t, ri.ZOOM)
    assert (tmp_path / "cache/dotfiles-setup/Zoom/zoom_amd64-latest.deb").is_file()


def test_zoom_is_installed_when_dpkg_lists_it(tmp_path):
    t, downloads = make(tmp_path, Machine(dpkg_listing="ii  zoom  6.0  amd64  Zoom\n"))
    assert ri.install_release(t, ri.ZOOM)
    assert downloads == []


def test_deb_install_failure_is_fixed_by_apt(tmp_path):
    machine = Machine(dpkg_listing="ii  zoom  6.0\n", fail=[("sudo", "dpkg")])
    t, _ = make(tmp_path, machine)
    assert ri._install_deb_or_fix_broken(t, tmp_path / "z.deb", "zoom")
    assert machine.ran("sudo", "apt-get", "-y", "--fix-broken", "install")


def test_deb_install_that_stays_broken_fails(tmp_path):
    machine = Machine(dpkg_listing="", fail=[("sudo", "dpkg")])
    t, _ = make(tmp_path, machine)
    assert not ri._install_deb_or_fix_broken(t, tmp_path / "z.deb", "zoom")


def test_slack_version_comes_from_the_downloads_page(tmp_path):
    machine = Machine()
    t, downloads = make(tmp_path, machine, fetch=lambda url: "<p>Version 4.35.0</p>")
    assert ri.install_release(t, ri.SLACK)
    assert downloads == ["https://downloads.slack-edge.com/desktop-releases/linux/x64/4.35.0/slack-desktop-4.35.0-amd64.deb"]


def test_slack_removes_the_unsigned_apt_source_files(tmp_path):
    machine = Machine()
    t, _ = make(tmp_path, machine, fetch=lambda url: "Version 4.35.0")
    ri.install_release(t, ri.SLACK)
    assert machine.ran("sudo", "rm", "-f", *ri.SLACK_APT_SOURCES)


def test_slack_without_a_version_downloads_nothing(tmp_path):
    t, downloads = make(tmp_path, Machine(), fetch=lambda url: "no version here")
    assert ri.install_release(t, ri.SLACK)
    assert downloads == []


JETBRAINS_JSON = '{"TBA":[{"downloads":{"linux":{"link":"https://example.com/jb/toolbox-2.5.tar.gz"}}}]}'


def test_jetbrains_installs_the_binary_with_exec_permission(tmp_path):
    t, downloads = make(tmp_path, Machine(), fetch=lambda url: JETBRAINS_JSON, payload=tarball("jb/jetbrains-toolbox"))
    assert ri.install_release(t, ri.JETBRAINS_TOOLBOX)
    binary = ri._jetbrains_binary(tmp_path)
    assert downloads == ["https://example.com/jb/toolbox-2.5.tar.gz"]
    assert binary.is_file()
    assert binary.stat().st_mode & 0o111


def test_jetbrains_archive_without_the_binary_installs_nothing(tmp_path):
    t, _ = make(tmp_path, Machine(), fetch=lambda url: JETBRAINS_JSON, payload=tarball("jb/readme"))
    assert ri.install_release(t, ri.JETBRAINS_TOOLBOX)
    assert not ri._jetbrains_binary(tmp_path).exists()


def test_jetbrains_with_an_existing_binary_is_skipped(tmp_path):
    binary = ri._jetbrains_binary(tmp_path)
    binary.parent.mkdir(parents=True)
    binary.write_text("")
    t, downloads = make(tmp_path, Machine())
    assert ri.install_release(t, ri.JETBRAINS_TOOLBOX)
    assert downloads == []


def zipball(member, mode):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        info = zipfile.ZipInfo(member)
        info.external_attr = (0o100000 | mode) << 16
        archive.writestr(info, "#!/bin/sh\n")
    return buffer.getvalue()


def test_istioctl_installs_the_binary_from_the_versioned_directory(tmp_path):
    machine = Machine()
    t, downloads = make(
        tmp_path, machine, fetch=lambda url: '{"tag_name": "1.20.0"}', payload=tarball("istio-1.20.0/bin/istioctl"),
    )
    assert ri.install_release(t, ri.ISTIOCTL)
    assert downloads == ["https://github.com/istio/istio/releases/download/1.20.0/istio-1.20.0-linux-amd64.tar.gz"]
    install = next(c for c in machine.commands if c[:2] == ["sudo", "install"])
    assert install[2].endswith("istio-1.20.0/bin/istioctl")


def test_zizmor_and_mcp_grafana_use_the_unprefixed_release_tag(tmp_path):
    for spec, asset in ((ri.ZIZMOR, "zizmor-x86_64-unknown-linux-gnu.tar.gz"), (ri.MCP_GRAFANA, "mcp-grafana_Linux_x86_64.tar.gz")):
        binary = spec.name
        t, downloads = make(tmp_path, Machine(), fetch=lambda url: '{"tag_name": "v0.5.1"}', payload=tarball(binary))
        assert ri.install_release(t, spec)
        assert downloads[0].endswith(f"/download/v0.5.1/{asset}")


def test_awscli_runs_the_extracted_installer_with_its_exec_bit(tmp_path):
    machine = Machine()
    t, downloads = make(tmp_path, machine, payload=zipball("aws/install", 0o755))
    assert ri.install_release(t, ri.AWSCLI)
    assert downloads == ["https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip"]
    installer = next(c for c in machine.commands if c[0] == "sudo" and c[1].endswith("aws/install"))
    assert installer


def test_awscli_extraction_keeps_the_installer_executable(tmp_path):
    artifact = tmp_path / "aws.zip"
    artifact.write_bytes(zipball("aws/install", 0o755))
    ri._extract_zip(artifact, tmp_path)
    assert (tmp_path / "aws/install").stat().st_mode & 0o111


def test_awscli_bad_zip_is_reported_and_skipped(tmp_path):
    machine = Machine()
    t, _ = make(tmp_path, machine, payload=b"not a zip")
    assert ri.install_release(t, ri.AWSCLI)
    assert not any(c[0] == "sudo" for c in machine.commands)


def test_release_installers_run_after_the_script_installers(tmp_path):
    names = [name for name, _ in tools.TOOL_INSTALLERS]
    assert names == [
        "oh-my-zsh", "sdkman", "nvm", "lazydocker", "zoom", "slack-desktop", "jetbrains-toolbox",
        "istioctl", "awscli", "zizmor", "mcp-grafana", "ruff", "coderabbit", "sonarqube-cli", "uv",
    ]
