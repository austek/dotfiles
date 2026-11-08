import hashlib
import io
import subprocess
import tarfile
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from dotfiles_setup import checksums, tools
from dotfiles_setup import release_installers as ri
from dotfiles_setup.log import Logger

LAZYDOCKER_URL = (
    "https://github.com/jesseduffield/lazydocker/releases/download/v0.25.2/lazydocker_0.25.2_Linux_x86_64.tar.gz"
)


@pytest.fixture(autouse=True)
def isolated_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.setattr("shutil.which", lambda name: None)
    monkeypatch.setattr("platform.machine", lambda: "x86_64")


PINNED_SPECS = [spec for _, spec in ri.RELEASE_SPECS]


@pytest.mark.parametrize("spec", PINNED_SPECS, ids=lambda spec: spec.name)
@pytest.mark.parametrize("arch", ["aarch64", "arm64"])
def test_a_non_x86_64_machine_downloads_nothing(tmp_path, monkeypatch, capsys, spec, arch):
    monkeypatch.setattr("platform.machine", lambda: arch)
    machine = Machine()
    t, downloads = make(tmp_path, machine)
    assert ri.install_release(t, spec)
    assert downloads == [] and not machine.ran("sudo")
    captured = capsys.readouterr()
    assert "x86_64 only" in captured.out and captured.err == ""


def test_upgrade_skips_a_non_x86_64_machine(tmp_path, monkeypatch):
    monkeypatch.setattr("platform.machine", lambda: "aarch64")
    machine = Machine(dpkg_listing=zoom_listing("7.2.1.5760"))
    t, downloads = make(tmp_path, machine)
    ri.upgrade_vendor_debs(t, {"zoom"})
    assert downloads == [] and not machine.ran("sudo")


def tarball(member):
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        info = tarfile.TarInfo(member)
        info.size = 3
        archive.addfile(info, io.BytesIO(b"bin"))
    return buffer.getvalue()


class Machine:
    """Records every command and answers dpkg -l from configurable state."""

    def __init__(self, dpkg_listing="", fail=(), codes=None):
        self.commands = []
        self.dpkg_listing = dpkg_listing
        self.fail = tuple(fail)
        self.codes = codes or {}

    def __call__(self, argv, **kwargs):
        self.commands.append(list(argv))
        if argv[:2] == ["dpkg", "-l"]:
            return SimpleNamespace(returncode=0, stdout=self.dpkg_listing, stderr="")
        for prefix, code in self.codes.items():
            if argv[: len(prefix)] == list(prefix):
                return SimpleNamespace(returncode=code, stdout="", stderr="")
        failed = any(argv[: len(prefix)] == list(prefix) for prefix in self.fail)
        return SimpleNamespace(returncode=1 if failed else 0, stdout="", stderr="")

    def ran(self, *prefix):
        return any(command[: len(prefix)] == list(prefix) for command in self.commands)


def make(tmp_path, machine, fetch=lambda url: "", payload=b"x", dry_run=False, redirect=lambda url: None, checksums=None):
    downloads = []

    def download(url, dest):
        downloads.append(url)
        if payload is None:
            raise OSError("offline")
        dest.write_bytes(payload)

    t = tools.Tooling(
        Logger(dry_run=dry_run, verbosity=1), tmp_path, run=machine, fetch=fetch, download=download, redirect=redirect,
        checksums=checksums,
    )
    return t, downloads


def test_installed_tool_is_skipped(tmp_path, monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/lazydocker")
    t, downloads = make(tmp_path, Machine())
    assert ri.install_release(t, ri.LAZYDOCKER)
    assert downloads == []


def test_dry_run_names_the_pinned_version_and_downloads_nothing(tmp_path, capsys):
    machine = Machine()
    t, downloads = make(tmp_path, machine, dry_run=True)
    assert ri.install_release(t, ri.LAZYDOCKER)
    assert downloads == [] and not machine.ran("sudo")
    assert f"Would download and install lazydocker v{ri.LAZYDOCKER_VERSION}" in capsys.readouterr().out


def payload_for(spec):
    """An artifact that installs when nothing verifies it."""
    if spec is ri.AWSCLI:
        return zipball("aws/install", 0o755)
    if spec is ri.JETBRAINS_TOOLBOX:
        return tarball("jb/jetbrains-toolbox")
    return tarball(spec.name)


def installed(spec, machine, home):
    return machine.ran("sudo") or ri._jetbrains_binary(home).exists()


def digest_of(payload):
    return hashlib.sha256(payload).hexdigest()


@pytest.mark.parametrize("spec", PINNED_SPECS, ids=lambda spec: spec.name)
def test_a_matching_digest_installs_and_a_mismatch_does_not(tmp_path, spec):
    payload, url = payload_for(spec), spec.resolve(None).url
    good, bad = Machine(), Machine()
    t, _ = make(tmp_path / "good", good, payload=payload, checksums={url: digest_of(payload)})
    ri.install_release(t, spec)
    t, _ = make(tmp_path / "bad", bad, payload=payload, checksums={url: "0" * 64})
    ri.install_release(t, spec)
    assert installed(spec, good, tmp_path / "good")
    assert not installed(spec, bad, tmp_path / "bad")


@pytest.mark.parametrize("spec", PINNED_SPECS, ids=lambda spec: spec.name)
def test_an_unlisted_url_installs_nothing(tmp_path, spec):
    machine = Machine()
    t, _ = make(tmp_path, machine, payload=payload_for(spec), checksums={})
    ri.install_release(t, spec)
    assert not installed(spec, machine, tmp_path)


@pytest.mark.parametrize("spec", PINNED_SPECS, ids=lambda spec: spec.name)
def test_a_tampered_cache_entry_is_replaced_by_a_verified_download(tmp_path, spec, capsys):
    payload, resolved = payload_for(spec), spec.resolve(None)
    cached = tmp_path / "cache" / "dotfiles-setup" / spec.name / resolved.cache_key
    cached.parent.mkdir(parents=True)
    cached.write_bytes(b"tampered")
    machine = Machine()
    t, downloads = make(tmp_path, machine, payload=payload, checksums={resolved.url: digest_of(payload)})
    ri.install_release(t, spec)
    assert downloads == [resolved.url]
    assert cached.read_bytes() == payload
    assert "Discarding the cached" in capsys.readouterr().out


@pytest.mark.parametrize("spec", PINNED_SPECS, ids=lambda spec: spec.name)
def test_a_rejected_download_is_never_cached(tmp_path, spec):
    resolved = spec.resolve(None)
    t, _ = make(tmp_path, Machine(), payload=payload_for(spec), checksums={resolved.url: "0" * 64})
    ri.install_release(t, spec)
    assert not (tmp_path / "cache" / "dotfiles-setup" / spec.name / resolved.cache_key).exists()


def test_lazydocker_download_failure_continues(tmp_path):
    machine = Machine()
    t, _ = make(tmp_path, machine, payload=None)
    assert ri.install_release(t, ri.LAZYDOCKER)
    assert not machine.ran("sudo", "install")


def test_a_download_failure_reports_the_underlying_cause(tmp_path, capsys):
    t, _ = make(tmp_path, Machine(), payload=None)
    ri.install_release(t, ri.LAZYDOCKER)
    assert "offline" in capsys.readouterr().err


def test_a_digest_mismatch_reports_the_digests(tmp_path, capsys):
    t, _ = make(tmp_path, Machine(), payload=tarball("lazydocker"), checksums={LAZYDOCKER_URL: "0" * 64})
    ri.install_release(t, ri.LAZYDOCKER)
    assert "digest mismatch" in capsys.readouterr().err


def test_lazydocker_bad_archive_continues_without_installing(tmp_path):
    machine = Machine()
    t, _ = make(tmp_path, machine, payload=b"not a tarball")
    assert ri.install_release(t, ri.LAZYDOCKER)
    assert not machine.ran("sudo", "install")


def test_lazydocker_installs_the_extracted_binary(tmp_path):
    machine = Machine()
    t, downloads = make(tmp_path, machine, payload=tarball("lazydocker"))
    assert ri.install_release(t, ri.LAZYDOCKER)
    assert downloads == [LAZYDOCKER_URL]
    install = next(c for c in machine.commands if c[:2] == ["sudo", "install"])
    assert install[2].endswith("/lazydocker")
    assert install[3] == "/usr/local/bin"


def test_lazydocker_install_failure_continues(tmp_path):
    machine = Machine(fail=[("sudo", "install")])
    t, _ = make(tmp_path, machine, payload=tarball("lazydocker"))
    assert ri.install_release(t, ri.LAZYDOCKER)


def test_second_run_uses_the_cached_download(tmp_path):
    first, downloads = make(tmp_path, Machine(), payload=tarball("lazydocker"))
    ri.install_release(first, ri.LAZYDOCKER)
    second, more = make(tmp_path, Machine(), payload=None)
    ri.install_release(second, ri.LAZYDOCKER)
    assert len(downloads) == 1
    assert more == []


def test_cache_drops_entries_for_other_versions(tmp_path):
    cache = tmp_path / "cache" / "dotfiles-setup" / "lazydocker"
    cache.mkdir(parents=True)
    (cache / "0.9.9.tar.gz").write_bytes(b"old")
    t, _ = make(tmp_path, Machine(), payload=tarball("lazydocker"))
    ri.install_release(t, ri.LAZYDOCKER)
    assert sorted(p.name for p in cache.iterdir()) == [f"{ri.LAZYDOCKER_VERSION}.tar.gz"]


def test_zoom_downloads_its_pinned_versioned_url(tmp_path):
    t, downloads = make(tmp_path, Machine())
    assert ri.install_release(t, ri.ZOOM)
    assert downloads == [f"https://cdn.zoom.us/prod/{ri.ZOOM_VERSION}/zoom_amd64.deb"]
    assert (tmp_path / f"cache/dotfiles-setup/Zoom/zoom_amd64-{ri.ZOOM_VERSION}.deb").is_file()


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


def test_slack_downloads_its_pinned_versioned_url(tmp_path):
    version = ri.SLACK_VERSION
    t, downloads = make(tmp_path, Machine())
    assert ri.install_release(t, ri.SLACK)
    assert downloads == [
        f"https://downloads.slack-edge.com/desktop-releases/linux/x64/{version}/slack-desktop-{version}-amd64.deb",
    ]


def test_slack_removes_the_unsigned_apt_source_files(tmp_path):
    machine = Machine()
    t, _ = make(tmp_path, machine)
    ri.install_release(t, ri.SLACK)
    assert machine.ran("sudo", "rm", "-f", *ri.SLACK_APT_SOURCES)


def test_jetbrains_installs_the_binary_with_exec_permission(tmp_path):
    t, downloads = make(tmp_path, Machine(), payload=tarball("jb/jetbrains-toolbox"))
    assert ri.install_release(t, ri.JETBRAINS_TOOLBOX)
    binary = ri._jetbrains_binary(tmp_path)
    assert downloads == [f"https://download.jetbrains.com/toolbox/jetbrains-toolbox-{ri.JETBRAINS_VERSION}.tar.gz"]
    assert binary.is_file()
    assert binary.stat().st_mode & 0o111


def test_jetbrains_archive_without_the_binary_installs_nothing(tmp_path):
    t, _ = make(tmp_path, Machine(), payload=tarball("jb/readme"))
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
    version = ri.ISTIOCTL_VERSION
    t, downloads = make(tmp_path, machine, payload=tarball(f"istio-{version}/bin/istioctl"))
    assert ri.install_release(t, ri.ISTIOCTL)
    assert downloads == [f"https://github.com/istio/istio/releases/download/{version}/istio-{version}-linux-amd64.tar.gz"]
    install = next(c for c in machine.commands if c[:2] == ["sudo", "install"])
    assert install[2].endswith(f"istio-{version}/bin/istioctl")


@pytest.mark.parametrize(("spec", "url"), [
    (ri.ZIZMOR, "https://github.com/zizmorcore/zizmor/releases/download/v1.32.0/zizmor-x86_64-unknown-linux-gnu.tar.gz"),
    (ri.MCP_GRAFANA, "https://github.com/grafana/mcp-grafana/releases/download/v2.2.0/mcp-grafana_Linux_x86_64.tar.gz"),
], ids=lambda value: getattr(value, "name", ""))
def test_zizmor_and_mcp_grafana_download_their_pinned_tag(tmp_path, spec, url):
    t, downloads = make(tmp_path, Machine(), payload=tarball(spec.name))
    assert ri.install_release(t, spec)
    assert downloads == [url]


@pytest.mark.parametrize("spec", PINNED_SPECS, ids=lambda spec: spec.name)
def test_every_pinned_url_has_a_shipped_digest(spec):
    table = checksums.load(Path(__file__).parent.parent / "packages" / checksums.FILE_NAME)
    assert spec.resolve(None).url in table


def test_awscli_runs_the_extracted_installer(tmp_path):
    machine = Machine()
    t, downloads = make(tmp_path, machine, payload=zipball("aws/install", 0o755))
    assert ri.install_release(t, ri.AWSCLI)
    assert downloads == [f"https://awscli.amazonaws.com/awscli-exe-linux-x86_64-{ri.AWSCLI_VERSION}.zip"]
    assert any(c[0] == "sudo" and c[1].endswith("aws/install") for c in machine.commands)


def test_awscli_extraction_keeps_the_installer_executable(tmp_path):
    artifact = tmp_path / "aws.zip"
    artifact.write_bytes(zipball("aws/install", 0o755))
    ri._extract_zip(artifact, tmp_path)
    assert (tmp_path / "aws/install").stat().st_mode & 0o111


def test_an_archive_the_filter_rejects_names_the_reason(tmp_path, capsys):
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        info = tarfile.TarInfo("../escape")
        info.size = 3
        archive.addfile(info, io.BytesIO(b"bin"))
    machine = Machine()
    t, _ = make(tmp_path, machine, payload=buffer.getvalue())
    ri.install_release(t, ri.LAZYDOCKER)
    assert not machine.ran("sudo")
    assert "Failed to extract lazydocker from tarball: OutsideDestinationError" in capsys.readouterr().err


def test_an_unexpected_zip_error_is_reported_not_raised(tmp_path, monkeypatch, capsys):
    def encrypted(_artifact, _temp_dir):
        raise RuntimeError("File is encrypted, password required for extraction")

    monkeypatch.setattr(ri, "_extract_zip", encrypted)
    machine = Machine()
    t, _ = make(tmp_path, machine, payload=zipball("aws/install", 0o755))
    assert ri.install_release(t, ri.AWSCLI)
    assert not machine.ran("sudo")
    assert "Failed to extract AWS CLI installer: RuntimeError" in capsys.readouterr().err


def test_awscli_bad_zip_is_reported_and_skipped(tmp_path):
    machine = Machine()
    t, _ = make(tmp_path, machine, payload=b"not a zip")
    assert ri.install_release(t, ri.AWSCLI)
    assert not any(c[0] == "sudo" for c in machine.commands)


def zoom_listing(version):
    return f"ii  zoom           {version}       amd64        Zoom Cloud Meetings\n"


@pytest.mark.parametrize(("installed", "latest", "current"), [
    ("7.2.5.6661", "7.2.5.6661", True),
    ("7.2.1.5760", "7.2.5.6661", False),
    ("7.2.1.5760", "7.2.1", False),
    ("4.41.105", "4.41.105", True),
    ("1:4.41.105-1", "4.41.105", True),
    ("4.41.105+build2", "4.41.105", True),
    (None, "7.2.5.6661", False),
])
def test_deb_is_current_compares_dpkg_and_vendor_versions(installed, latest, current):
    assert ri.deb_is_current(installed, latest) is current


NOT_OLDER = [("dpkg", "--compare-versions")]


def test_upgrade_installs_the_zoom_pin_once_when_the_installed_version_is_older(tmp_path):
    machine = Machine(dpkg_listing=zoom_listing("7.2.1.5760"))
    t, downloads = make(tmp_path, machine)
    ri.upgrade_vendor_debs(t, {"zoom"})
    assert downloads == [ri.ZOOM_URL]
    assert machine.ran("dpkg", "--compare-versions", "7.2.1.5760", "lt", ri.ZOOM_VERSION)
    assert sum(c[:3] == ["sudo", "dpkg", "-i"] for c in machine.commands) == 1


def test_upgrade_never_downgrades_a_zoom_newer_than_the_pin(tmp_path):
    machine = Machine(dpkg_listing=zoom_listing("9.0.0.1"), fail=NOT_OLDER)
    t, downloads = make(tmp_path, machine)
    ri.upgrade_vendor_debs(t, {"zoom"})
    assert downloads == []
    assert not machine.ran("sudo")


def test_upgrade_reports_a_version_dpkg_cannot_compare(tmp_path, capsys):
    machine = Machine(dpkg_listing=zoom_listing("bad version!"), codes={("dpkg", "--compare-versions"): 2})
    t, downloads = make(tmp_path, machine)
    ri.upgrade_vendor_debs(t, {"zoom"})
    assert downloads == [] and not machine.ran("sudo")
    assert "Could not compare Zoom" in capsys.readouterr().out


def test_upgrade_refuses_a_zoom_pin_with_the_wrong_digest(tmp_path):
    machine = Machine(dpkg_listing=zoom_listing("7.2.1.5760"))
    t, _ = make(tmp_path, machine, payload=b"deb", checksums={ri.ZOOM_URL: "0" * 64})
    ri.upgrade_vendor_debs(t, {"zoom"})
    assert not machine.ran("sudo", "dpkg", "-i")


@pytest.mark.skipif(not Path("/usr/bin/dpkg").exists(), reason="needs dpkg")
@pytest.mark.parametrize(("installed", "expected"), [
    ("7.2.1.5760", True), ("9.0.0.1", False), (ri.ZOOM_VERSION, False), ("bad version!", None),
])
def test_is_older_follows_real_dpkg_ordering(tmp_path, installed, expected):
    t = tools.Tooling(Logger(dry_run=False, verbosity=0), tmp_path, run=subprocess.run)
    assert ri._is_older(t, installed, ri.ZOOM_VERSION) is expected


def test_upgrade_skips_zoom_at_the_pin(tmp_path):
    machine = Machine(dpkg_listing=zoom_listing(ri.ZOOM_VERSION), fail=NOT_OLDER)
    t, downloads = make(tmp_path, machine)
    ri.upgrade_vendor_debs(t, {"zoom"})
    assert downloads == []


def test_upgrade_leaves_an_absent_package_to_the_install(tmp_path):
    machine = Machine()
    t, downloads = make(tmp_path, machine)
    ri.upgrade_vendor_debs(t, {"zoom"})
    assert downloads == []
    assert not machine.ran("dpkg", "--compare-versions")


def test_upgrade_ignores_unwanted_vendor_debs(tmp_path):
    machine = Machine(dpkg_listing=zoom_listing("7.2.1.5760"))
    t, downloads = make(tmp_path, machine)
    ri.upgrade_vendor_debs(t, {"slack-desktop"})
    assert downloads == []


def test_upgrade_dry_run_downloads_and_installs_nothing(tmp_path, capsys):
    machine = Machine(dpkg_listing=zoom_listing("7.2.1.5760"))
    t, downloads = make(tmp_path, machine, dry_run=True)
    ri.upgrade_vendor_debs(t, {"zoom"})
    assert downloads == []
    assert not machine.ran("sudo")
    assert f"Would upgrade Zoom from v7.2.1.5760 to v{ri.ZOOM_VERSION}" in capsys.readouterr().out


def test_upgrade_leaves_an_installed_slack_to_its_apt_repo(tmp_path):
    machine = Machine(dpkg_listing="ii  slack-desktop  4.35.0  amd64  Slack\n")
    t, downloads = make(tmp_path, machine)
    ri.upgrade_vendor_debs(t, {"slack-desktop"})
    assert downloads == []
    assert not machine.ran("sudo")


def test_only_zoom_is_upgradable():
    assert [package for package, _ in ri.UPGRADABLE_DEBS] == ["zoom"]


def test_install_tools_without_upgrade_skips_an_installed_zoom(tmp_path):
    machine = Machine(dpkg_listing=zoom_listing("7.2.1.5760"))
    t, downloads = make(tmp_path, machine)
    assert tools.install_tools(t, {"zoom"})
    assert downloads == []


def test_install_tools_with_upgrade_installs_the_pin_over_an_outdated_zoom(tmp_path):
    machine = Machine(dpkg_listing=zoom_listing("7.2.1.5760"))
    t, downloads = make(tmp_path, machine)
    assert tools.install_tools(t, {"zoom"}, upgrade=True)
    assert downloads == [ri.ZOOM_URL]


def test_release_installers_run_after_the_script_installers(tmp_path):
    names = [name for name, _ in tools.TOOL_INSTALLERS]
    assert names == [
        "oh-my-zsh", "sdkman", "nvm", "lazydocker", "zoom", "slack-desktop", "jetbrains-toolbox",
        "istioctl", "awscli", "zizmor", "mcp-grafana", "coderabbit", "sonarqube-cli", "uv",
        "antigravity-ide",
    ]
