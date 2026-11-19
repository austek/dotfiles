import hashlib
import io
import subprocess
import tarfile
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from dotfiles_setup import checksums, tools
from dotfiles_setup import deb_helpers as dh
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
    ri.install_release(t, spec)
    assert downloads == []
    assert not machine.ran("sudo")
    captured = capsys.readouterr()
    assert "x86_64 only" in captured.out
    assert captured.err == ""


def test_upgrade_skips_a_non_x86_64_machine(tmp_path, monkeypatch):
    monkeypatch.setattr("platform.machine", lambda: "aarch64")
    machine = Machine(dpkg_listing=zoom_listing("7.2.1.5760"))
    t, downloads = make(tmp_path, machine)
    ri.upgrade_vendor_debs(t, {"zoom"})
    assert downloads == []
    assert not machine.ran("sudo")


def tarball(member):
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        info = tarfile.TarInfo(member)
        info.size = 3
        archive.addfile(info, io.BytesIO(b"bin"))
    return buffer.getvalue()


class Machine:
    """Records every command and answers dpkg -l from configurable state."""

    def __init__(self, dpkg_listing="", fail=(), codes=None, listing_after_fix=None):
        self.commands = []
        self.dpkg_listing = dpkg_listing
        self.fail = tuple(fail)
        self.codes = codes or {}
        self.listing_after_fix = listing_after_fix

    def __call__(self, argv, **kwargs):
        self.commands.append(list(argv))
        if argv[:4] == ["sudo", "apt-get", "-y", "--fix-broken"] and self.listing_after_fix is not None:
            self.dpkg_listing = self.listing_after_fix
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


def test_installed_tool_is_skipped(tmp_path):
    (tmp_path / ".local" / "bin").mkdir(parents=True)
    (tmp_path / ".local" / "bin" / "lazydocker").write_text("")
    t, downloads = make(tmp_path, Machine())
    ri.install_release(t, ri.LAZYDOCKER)
    assert downloads == []


def test_dry_run_names_the_pinned_version_and_downloads_nothing(tmp_path, capsys):
    machine = Machine()
    t, downloads = make(tmp_path, machine, dry_run=True)
    ri.install_release(t, ri.LAZYDOCKER)
    assert downloads == []
    assert not machine.ran("sudo")
    assert f"Would download and install lazydocker v{ri.SPEC_DATA["lazydocker"].version}" in capsys.readouterr().out


def payload_for(spec):
    """An artifact that installs when nothing verifies it."""
    if spec is ri.AWSCLI:
        return zipball("aws/install", 0o755)
    if spec is ri.JETBRAINS_TOOLBOX:
        return tarball("jb/jetbrains-toolbox")
    return tarball(spec.name)


def installed(spec, machine, home):
    if spec.kind == "deb":
        return machine.ran("sudo", "dpkg", "-i")
    if spec is ri.AWSCLI:
        return any(command[0].endswith("aws/install") for command in machine.commands)
    if spec.binary:
        return (home / ".local" / "bin" / spec.binary).exists()
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
    ri.install_release(t, ri.LAZYDOCKER)
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
    ri.install_release(t, ri.LAZYDOCKER)
    assert not machine.ran("sudo", "install")


def test_lazydocker_downloads_the_pinned_archive(tmp_path):
    t, downloads = make(tmp_path, Machine(), payload=tarball("lazydocker"))
    ri.install_release(t, ri.LAZYDOCKER)
    assert downloads == [LAZYDOCKER_URL]


def test_a_tarball_without_the_binary_installs_nothing_and_says_so(tmp_path, capsys):
    machine = Machine()
    t, _ = make(tmp_path, machine, payload=tarball("README"))
    ri.install_release(t, dict(ri.RELEASE_SPECS)["flux"])
    captured = capsys.readouterr()
    assert not machine.ran("sudo", "install")
    assert "Failed to install flux" in captured.out + captured.err


def tarball_of(*members):
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        for name, is_dir in members:
            info = tarfile.TarInfo(name)
            info.type = tarfile.DIRTYPE if is_dir else tarfile.REGTYPE
            info.size = 0 if is_dir else 3
            archive.addfile(info, None if is_dir else io.BytesIO(b"bin"))
    return buffer.getvalue()


def test_a_directory_named_like_the_binary_is_never_installed(tmp_path):
    t, _ = make(tmp_path, Machine(), payload=tarball_of(("helm", True), ("linux-amd64/helm", False)))
    ri.install_release(t, dict(ri.RELEASE_SPECS)["helm"])
    assert (tmp_path / ".local" / "bin" / "helm").read_bytes() == b"bin"


def test_equally_deep_matches_pick_the_first_path_in_sorted_order(tmp_path):
    payload = io.BytesIO()
    with tarfile.open(fileobj=payload, mode="w:gz") as archive:
        for name, body in (("b/helm", b"from-b"), ("a/helm", b"from-a")):
            info = tarfile.TarInfo(name)
            info.size = len(body)
            archive.addfile(info, io.BytesIO(body))
    t, _ = make(tmp_path, Machine(), payload=payload.getvalue())
    ri.install_release(t, dict(ri.RELEASE_SPECS)["helm"])
    assert (tmp_path / ".local" / "bin" / "helm").read_bytes() == b"from-a"


def test_lazydocker_install_failure_continues(tmp_path):
    (tmp_path / ".local").write_text("a file where the directory should be")
    t, _ = make(tmp_path, Machine(), payload=tarball("lazydocker"))
    ri.install_release(t, ri.LAZYDOCKER)


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
    assert sorted(p.name for p in cache.iterdir()) == [f"{ri.SPEC_DATA["lazydocker"].version}.tar.gz"]


def test_zoom_downloads_its_pinned_versioned_url(tmp_path):
    t, downloads = make(tmp_path, Machine())
    ri.install_release(t, ri.ZOOM)
    assert downloads == [f"https://cdn.zoom.us/prod/{ri.SPEC_DATA["zoom"].version}/zoom_amd64.deb"]
    assert (tmp_path / f"cache/dotfiles-setup/Zoom/zoom_amd64-{ri.SPEC_DATA["zoom"].version}.deb").is_file()


def test_zoom_is_installed_when_dpkg_lists_it(tmp_path):
    t, downloads = make(tmp_path, Machine(dpkg_listing="ii  zoom  6.0  amd64  Zoom\n"))
    ri.install_release(t, ri.ZOOM)
    assert downloads == []


def test_deb_install_failure_is_fixed_by_apt(tmp_path):
    machine = Machine(fail=[("sudo", "dpkg")], listing_after_fix="ii  zoom  6.0\n")
    t, _ = make(tmp_path, machine)
    assert dh._install_deb_or_fix_broken(t, tmp_path / "z.deb", "zoom")
    assert machine.ran("sudo", "apt-get", "-y", "--fix-broken", "install")


def test_a_failed_upgrade_that_leaves_the_old_version_is_not_a_success(tmp_path):
    machine = Machine(dpkg_listing=zoom_listing("7.2.1.5760"), fail=[("sudo", "dpkg")])
    t, _ = make(tmp_path, machine)
    assert not dh._install_deb_or_fix_broken(t, tmp_path / "z.deb", "zoom")


def test_a_failed_upgrade_that_apt_completes_is_a_success(tmp_path):
    machine = Machine(
        dpkg_listing=zoom_listing("7.2.1.5760"), fail=[("sudo", "dpkg")], listing_after_fix=zoom_listing(ri.SPEC_DATA["zoom"].version),
    )
    t, _ = make(tmp_path, machine)
    assert dh._install_deb_or_fix_broken(t, tmp_path / "z.deb", "zoom")


def test_deb_install_that_stays_broken_fails(tmp_path):
    machine = Machine(dpkg_listing="", fail=[("sudo", "dpkg")])
    t, _ = make(tmp_path, machine)
    assert not dh._install_deb_or_fix_broken(t, tmp_path / "z.deb", "zoom")


def test_jetbrains_installs_the_binary_with_exec_permission(tmp_path):
    t, downloads = make(tmp_path, Machine(), payload=tarball("jb/jetbrains-toolbox"))
    ri.install_release(t, ri.JETBRAINS_TOOLBOX)
    binary = ri._jetbrains_binary(tmp_path)
    assert downloads == [f"https://download.jetbrains.com/toolbox/jetbrains-toolbox-{ri.SPEC_DATA["jetbrains-toolbox"].version}.tar.gz"]
    assert binary.is_file()
    assert binary.stat().st_mode & 0o111


def test_jetbrains_archive_without_the_binary_installs_nothing(tmp_path):
    t, _ = make(tmp_path, Machine(), payload=tarball("jb/readme"))
    ri.install_release(t, ri.JETBRAINS_TOOLBOX)
    assert not ri._jetbrains_binary(tmp_path).exists()


def test_jetbrains_with_an_existing_binary_is_skipped(tmp_path):
    binary = ri._jetbrains_binary(tmp_path)
    binary.parent.mkdir(parents=True)
    binary.write_text("")
    t, downloads = make(tmp_path, Machine())
    ri.install_release(t, ri.JETBRAINS_TOOLBOX)
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
    version = ri.SPEC_DATA["istioctl"].version
    t, downloads = make(tmp_path, machine, payload=tarball(f"istio-{version}/bin/istioctl"))
    ri.install_release(t, ri.ISTIOCTL)
    assert downloads == [f"https://github.com/istio/istio/releases/download/{version}/istio-{version}-linux-amd64.tar.gz"]
    assert (user_bin(tmp_path) / "istioctl").read_bytes() == b"bin"
    assert (user_bin(tmp_path) / "istioctl").stat().st_mode & 0o777 == 0o755
    assert not machine.ran("sudo")


@pytest.mark.parametrize(("spec", "url"), [
    (ri.ZIZMOR, "https://github.com/zizmorcore/zizmor/releases/download/v1.32.0/zizmor-x86_64-unknown-linux-gnu.tar.gz"),
    (ri.MCP_GRAFANA, "https://github.com/grafana/mcp-grafana/releases/download/v2.2.0/mcp-grafana_Linux_x86_64.tar.gz"),
], ids=lambda value: getattr(value, "name", ""))
def test_zizmor_and_mcp_grafana_download_their_pinned_tag(tmp_path, spec, url):
    t, downloads = make(tmp_path, Machine(), payload=tarball(spec.name))
    ri.install_release(t, spec)
    assert downloads == [url]


@pytest.mark.parametrize("spec", PINNED_SPECS, ids=lambda spec: spec.name)
def test_every_pinned_url_has_a_shipped_digest(spec):
    table = checksums.load(Path(__file__).parent.parent / "packages" / checksums.FILE_NAME)
    assert spec.resolve(None).url in table


def test_awscli_runs_the_extracted_installer(tmp_path):
    machine = Machine()
    t, downloads = make(tmp_path, machine, payload=zipball("aws/install", 0o755))
    ri.install_release(t, ri.AWSCLI)
    assert downloads == [f"https://awscli.amazonaws.com/awscli-exe-linux-x86_64-{ri.SPEC_DATA["awscli"].version}.zip"]
    assert not machine.ran("sudo")
    [command] = [c for c in machine.commands if c[0].endswith("aws/install")]
    assert command[1:] == ["-i", str(tmp_path / ".local" / "aws-cli"), "-b", str(user_bin(tmp_path)), "--update"]


def test_awscli_extraction_keeps_the_installer_executable(tmp_path):
    artifact = tmp_path / "aws.zip"
    artifact.write_bytes(zipball("aws/install", 0o755))
    ri._extract_zip(artifact, tmp_path)
    assert (tmp_path / "aws/install").stat().st_mode & 0o111


def test_zip_extraction_never_chmods_outside_the_target_dir(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    victim = tmp_path / "victim"
    victim.write_text("keep")
    victim.chmod(0o600)
    artifact = tmp_path / "evil.zip"
    artifact.write_bytes(zipball("../victim", 0o777))
    ri._extract_zip(artifact, work)
    assert victim.stat().st_mode & 0o777 == 0o600
    assert (work / "victim").stat().st_mode & 0o777 == 0o777


def zip_with(path, entries):
    with zipfile.ZipFile(path, "w") as archive:
        for name, mode, body in entries:
            info = zipfile.ZipInfo(name)
            info.external_attr = mode << 16
            archive.writestr(info, body)


def test_zip_extraction_leaves_directories_writable(tmp_path):
    artifact, out = tmp_path / "a.zip", tmp_path / "out"
    zip_with(artifact, [("d/", 0o40500, ""), ("d/f", 0o100755, "x")])
    ri._extract_zip(artifact, out)
    assert (out / "d").stat().st_mode & 0o200
    assert (out / "d/f").stat().st_mode & 0o111


def test_zip_symlink_members_are_not_materialised_as_links(tmp_path):
    artifact, out = tmp_path / "a.zip", tmp_path / "out"
    zip_with(artifact, [("l", 0o120777, "/etc/passwd")])
    ri._extract_zip(artifact, out)
    assert not (out / "l").is_symlink()


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
    ri.install_release(t, ri.AWSCLI)
    assert machine.commands == []
    assert "Failed to extract AWS CLI installer: RuntimeError" in capsys.readouterr().err


def test_awscli_bad_zip_is_reported_and_skipped(tmp_path):
    machine = Machine()
    t, _ = make(tmp_path, machine, payload=b"not a zip")
    ri.install_release(t, ri.AWSCLI)
    assert machine.commands == []


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
    assert dh.deb_is_current(installed, latest) is current


NOT_OLDER = [("dpkg", "--compare-versions")]


def test_upgrade_installs_the_zoom_pin_once_when_the_installed_version_is_older(tmp_path):
    machine = Machine(dpkg_listing=zoom_listing("7.2.1.5760"))
    t, downloads = make(tmp_path, machine)
    ri.upgrade_vendor_debs(t, {"zoom"})
    assert downloads == [ri.SPEC_DATA["zoom"].download_url]
    assert machine.ran("dpkg", "--compare-versions", "7.2.1.5760", "lt", ri.SPEC_DATA["zoom"].version)
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
    assert downloads == []
    assert not machine.ran("sudo")
    assert "Could not compare Zoom" in capsys.readouterr().out


def test_upgrade_refuses_a_zoom_pin_with_the_wrong_digest(tmp_path):
    machine = Machine(dpkg_listing=zoom_listing("7.2.1.5760"))
    t, _ = make(tmp_path, machine, payload=b"deb", checksums={ri.SPEC_DATA["zoom"].download_url: "0" * 64})
    ri.upgrade_vendor_debs(t, {"zoom"})
    assert not machine.ran("sudo", "dpkg", "-i")


@pytest.mark.skipif(not Path("/usr/bin/dpkg").exists(), reason="needs dpkg")
@pytest.mark.parametrize(("installed", "expected"), [
    ("7.2.1.5760", True), ("9.0.0.1", False), (ri.SPEC_DATA["zoom"].version, False), ("bad version!", None),
])
def test_is_older_follows_real_dpkg_ordering(tmp_path, installed, expected):
    t = tools.Tooling(Logger(dry_run=False, verbosity=0), tmp_path, run=subprocess.run)
    assert dh._is_older(t, installed, ri.SPEC_DATA["zoom"].version) is expected


def test_upgrade_skips_zoom_at_the_pin(tmp_path):
    machine = Machine(dpkg_listing=zoom_listing(ri.SPEC_DATA["zoom"].version), fail=NOT_OLDER)
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
    ri.upgrade_vendor_debs(t, set())
    assert downloads == []


def test_upgrade_dry_run_downloads_and_installs_nothing(tmp_path, capsys):
    machine = Machine(dpkg_listing=zoom_listing("7.2.1.5760"))
    t, downloads = make(tmp_path, machine, dry_run=True)
    ri.upgrade_vendor_debs(t, {"zoom"})
    assert downloads == []
    assert not machine.ran("sudo")
    assert f"Would upgrade Zoom from v7.2.1.5760 to v{ri.SPEC_DATA["zoom"].version}" in capsys.readouterr().out


def test_zoom_is_the_upgradable_deb():
    assert [package for package, _ in ri.UPGRADABLE_DEBS] == ["zoom"]


class ChipMachine(Machine):
    """Answers `--version` for the chip at `path`; any other chip path reports a stale 0.0.1."""

    def __init__(self, version, path, **kwargs):
        super().__init__(**kwargs)
        self.version = version
        self.path = path

    def __call__(self, argv, **kwargs):
        result = super().__call__(argv, **kwargs)
        if argv[1:] == ["--version"] and argv[0].endswith("chip"):
            stdout = self.version if argv[0] == str(self.path) else "0.0.1"
            return SimpleNamespace(returncode=0, stdout=stdout, stderr="")
        return result


@pytest.fixture
def managed_chip(tmp_path):
    (tmp_path / ".local" / "bin").mkdir(parents=True)
    path = tmp_path / ".local" / "bin" / "chip"
    path.write_text("")
    return path


def chip_url(version):
    return f"https://github.com/collibra/chip/releases/download/v{version}/chip-{version}-linux-amd64"


def test_chip_downloads_the_raw_pinned_binary(tmp_path):
    t, downloads = make(tmp_path, Machine(), payload=b"\x7fELF")
    ri.install_release(t, ri.CHIP)
    assert downloads == [chip_url(ri.SPEC_DATA["chip"].version)]


def test_chip_install_failure_warns_and_continues(tmp_path, capsys):
    (tmp_path / ".local").write_text("a file where the directory should be")
    t, _ = make(tmp_path, Machine(), payload=b"\x7fELF")
    ri.install_release(t, ri.CHIP)
    assert "Failed to install chip." in capsys.readouterr().err


def test_upgrade_installs_the_chip_pin_over_an_older_binary(tmp_path, managed_chip):
    machine = ChipMachine("0.0.60\nCollibra MCP Server 0.0.60\n", managed_chip)
    t, downloads = make(tmp_path, machine, payload=b"new")
    ri.upgrade_user_binaries(t, {"chip"})
    assert downloads == [chip_url(ri.SPEC_DATA["chip"].version)]
    assert machine.ran("dpkg", "--compare-versions", "0.0.60", "lt", ri.SPEC_DATA["chip"].version)
    assert managed_chip.read_bytes() == b"new"
    assert not machine.ran("sudo")


@pytest.mark.parametrize("installed", ["0.0.67", "0.1.0"])
def test_upgrade_leaves_a_chip_at_or_above_the_pin(tmp_path, managed_chip, installed):
    machine = ChipMachine(installed, managed_chip, fail=NOT_OLDER)
    t, downloads = make(tmp_path, machine)
    ri.upgrade_user_binaries(t, {"chip"})
    assert downloads == []
    assert not machine.ran("sudo")


def test_upgrade_reads_the_managed_chip_not_a_stale_one_on_path(tmp_path, managed_chip, monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: str(tmp_path / "local" / "chip"))
    machine = ChipMachine("0.1.0", managed_chip, fail=NOT_OLDER)
    t, downloads = make(tmp_path, machine)
    ri.upgrade_user_binaries(t, {"chip"})
    assert downloads == []
    assert not machine.ran("sudo")
    assert not machine.ran("chip")


def test_upgrade_skips_chip_when_it_is_not_installed_or_not_wanted(tmp_path, managed_chip):
    machine = ChipMachine("0.0.1", managed_chip)
    t, downloads = make(tmp_path, machine)
    ri.upgrade_user_binaries(t, set())
    managed_chip.unlink()
    ri.upgrade_user_binaries(t, {"chip"})
    assert downloads == []
    assert not machine.ran(str(managed_chip))


def test_install_tools_without_upgrade_skips_an_installed_zoom(tmp_path):
    machine = Machine(dpkg_listing=zoom_listing("7.2.1.5760"))
    t, downloads = make(tmp_path, machine)
    assert tools.install_system_tools(t, {"zoom"})
    assert downloads == []


def test_install_tools_with_upgrade_installs_the_pin_over_an_outdated_zoom(tmp_path):
    machine = Machine(dpkg_listing=zoom_listing("7.2.1.5760"))
    t, downloads = make(tmp_path, machine)
    assert tools.install_system_tools(t, {"zoom"}, upgrade=True)
    assert downloads == [ri.SPEC_DATA["zoom"].download_url]


def test_user_stage_tools_never_run_the_sudo_release_installers(tmp_path):
    machine = Machine()
    t, downloads = make(tmp_path, machine, payload=b"\x7fELF")
    assert tools.install_tools(
        t, {"chip", "zoom", "istioctl", "awscli", "lazydocker", "zizmor", "mcp-grafana", "kubectl", "helm", "flux",
            "kubeconform", "sops"},
    )
    assert downloads == []
    assert not machine.ran("sudo")


def test_release_installers_run_after_the_script_installers(tmp_path):
    names = [name for name, _ in tools.TOOL_INSTALLERS]
    assert names == [
        "oh-my-zsh", "sdkman", "nvm", "jetbrains-toolbox", "coderabbit", "sonarqube-cli", "uv",
    ]
    assert [name for name, _ in tools.SYSTEM_TOOL_INSTALLERS] == ["zoom", "antigravity-ide"]


BINARY_PACKAGES = (
    "lazydocker", "istioctl", "awscli", "zizmor", "mcp-grafana", "chip", "kubectl", "helm", "flux", "kubeconform", "sops",
)


class Tracker:
    def __init__(self):
        self.entries = []

    def track(self, entry, *, dry_run):
        self.entries.append(entry)


def user_bin(tmp_path):
    return tmp_path / ".local" / "bin"


def test_only_zoom_keeps_a_sudo_release_install():
    assert ri.PRIVILEGED_PACKAGES == {"zoom"}
    assert [p for p, _ in ri.SYSTEM_SPECS] == ["zoom"]
    assert [p for p, _ in ri.USER_BINARY_SPECS] == list(BINARY_PACKAGES)


def test_lazydocker_installs_into_the_user_bin_dir_without_sudo(tmp_path):
    machine = Machine()
    t, _ = make(tmp_path, machine, payload=tarball("lazydocker"))
    ri.install_release(t, ri.LAZYDOCKER)
    installed_binary = user_bin(tmp_path) / "lazydocker"
    assert installed_binary.read_bytes() == b"bin"
    assert installed_binary.stat().st_mode & 0o777 == 0o755
    assert not machine.ran("sudo")


def test_a_nested_archive_member_installs_into_the_user_bin_dir(tmp_path):
    t, _ = make(tmp_path, Machine(), payload=tarball("linux-amd64/helm"))
    ri.install_release(t, dict(ri.RELEASE_SPECS)["helm"])
    assert (user_bin(tmp_path) / "helm").is_file()


def test_a_raw_binary_installs_under_its_own_name_in_the_user_bin_dir(tmp_path):
    machine = Machine()
    t, _ = make(tmp_path, machine, payload=b"\x7fELF")
    ri.install_release(t, ri.CHIP)
    assert (user_bin(tmp_path) / "chip").read_bytes() == b"\x7fELF"
    assert not machine.ran("sudo")


def test_an_archive_without_the_binary_installs_nothing(tmp_path, capsys):
    t, _ = make(tmp_path, Machine(), payload=tarball("README"))
    ri.install_release(t, dict(ri.RELEASE_SPECS)["flux"])
    assert not (user_bin(tmp_path) / "flux").exists()
    assert "Failed to install flux" in capsys.readouterr().err


def test_a_binary_replaces_an_older_copy_atomically_and_leaves_no_temp_file(tmp_path):
    (user_bin(tmp_path)).mkdir(parents=True)
    (user_bin(tmp_path) / "chip").write_bytes(b"old")
    t, _ = make(tmp_path, ChipMachine("0.0.1", user_bin(tmp_path) / "chip"), payload=b"new")
    ri.upgrade_user_binaries(t, {"chip"})
    assert (user_bin(tmp_path) / "chip").read_bytes() == b"new"
    assert [p.name for p in user_bin(tmp_path).iterdir()] == ["chip"]


def test_the_user_bin_dir_is_created_with_mode_0755(tmp_path):
    t, _ = make(tmp_path, Machine(), payload=b"\x7fELF")
    ri.install_user_binaries(t, {"chip"}, Tracker())
    assert user_bin(tmp_path).stat().st_mode & 0o777 == 0o755


def test_each_install_is_tracked_with_the_digest_of_the_installed_file(tmp_path):
    tracker = Tracker()
    t, _ = make(tmp_path, Machine(), payload=b"\x7fELF")
    ri.install_user_binaries(t, {"chip"}, tracker)
    assert tracker.entries == [
        f"DIR_CREATED:{user_bin(tmp_path)}",
        f"BIN_INSTALLED:{user_bin(tmp_path) / 'chip'}|{digest_of(b'\x7fELF')}",
    ]


def test_an_existing_user_bin_dir_is_not_tracked_as_created(tmp_path):
    user_bin(tmp_path).mkdir(parents=True)
    tracker = Tracker()
    t, _ = make(tmp_path, Machine(), payload=b"\x7fELF")
    ri.install_user_binaries(t, {"chip"}, tracker)
    assert [e.split(":")[0] for e in tracker.entries] == ["BIN_INSTALLED"]


def test_a_failed_install_is_not_tracked(tmp_path):
    tracker = Tracker()
    t, _ = make(tmp_path, Machine(), payload=tarball("README"))
    ri.install_user_binaries(t, {"flux"}, tracker)
    assert [e.split(":")[0] for e in tracker.entries] == ["DIR_CREATED"]


def test_a_binary_already_in_the_user_bin_dir_is_skipped(tmp_path):
    user_bin(tmp_path).mkdir(parents=True)
    (user_bin(tmp_path) / "chip").write_bytes(b"mine")
    tracker = Tracker()
    t, downloads = make(tmp_path, Machine())
    ri.install_user_binaries(t, {"chip"}, tracker)
    assert downloads == []
    assert tracker.entries == []


def test_a_copy_elsewhere_on_path_does_not_count_as_installed(tmp_path, monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name, path=None: f"/usr/local/bin/{name}")
    t, downloads = make(tmp_path, Machine(), payload=b"\x7fELF")
    ri.install_user_binaries(t, {"chip"}, Tracker())
    assert len(downloads) == 1


def test_unwanted_binaries_are_not_installed(tmp_path):
    t, downloads = make(tmp_path, Machine(), payload=b"\x7fELF")
    ri.install_user_binaries(t, {"vim"}, Tracker())
    assert downloads == []
    assert not user_bin(tmp_path).exists()


def test_dry_run_creates_nothing_and_tracks_nothing(tmp_path, capsys):
    tracker = Tracker()
    t, downloads = make(tmp_path, Machine(), dry_run=True)
    ri.install_user_binaries(t, {"chip"}, tracker)
    assert downloads == []
    assert tracker.entries == []
    assert not user_bin(tmp_path).exists()
    assert "Would download and install chip" in capsys.readouterr().out


def test_a_file_where_the_user_bin_parent_should_be_fails_the_step_cleanly(tmp_path, capsys):
    (tmp_path / ".local").write_text("a file")
    t, downloads = make(tmp_path, Machine(), payload=b"\x7fELF")
    assert ri.install_user_binaries(t, {"chip"}, Tracker()) is False
    assert downloads == []
    assert "Traceback" not in capsys.readouterr().err


def test_a_broken_symlink_as_the_user_bin_dir_fails_the_step_cleanly(tmp_path, capsys):
    (tmp_path / ".local").mkdir()
    user_bin(tmp_path).symlink_to(tmp_path / "nowhere")
    tracker = Tracker()
    t, _ = make(tmp_path, Machine(), payload=b"\x7fELF")
    assert tools.install_user_binaries(t, {"chip"}, tracker) is False
    assert tracker.entries == []
    assert "Traceback" not in capsys.readouterr().err


def test_a_failed_directory_step_warns_through_the_logger(tmp_path, capsys):
    (tmp_path / ".local").write_text("a file")
    t, _ = make(tmp_path, Machine(), payload=b"\x7fELF")
    ri.install_user_binaries(t, {"chip"}, Tracker())
    captured = capsys.readouterr()
    assert f"Could not create {user_bin(tmp_path)}" in captured.out + captured.err


def test_a_successful_run_reports_success(tmp_path):
    t, _ = make(tmp_path, Machine(), payload=b"\x7fELF")
    assert ri.install_user_binaries(t, {"chip"}, Tracker()) is True
    assert ri.install_user_binaries(t, {"vim"}, Tracker()) is True


def test_a_non_x86_64_machine_creates_no_user_bin_dir_and_tracks_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr("platform.machine", lambda: "aarch64")
    tracker = Tracker()
    t, downloads = make(tmp_path, Machine(), payload=b"\x7fELF")
    assert ri.install_user_binaries(t, {"chip"}, tracker) is True
    assert not user_bin(tmp_path).exists()
    assert tracker.entries == []
    assert downloads == []


def test_the_user_bin_dir_has_mode_0755_under_a_restrictive_umask(tmp_path):
    import os
    t, _ = make(tmp_path, Machine(), payload=b"\x7fELF")
    previous = os.umask(0o077)
    try:
        ri.install_user_binaries(t, {"chip"}, Tracker())
    finally:
        os.umask(previous)
    assert user_bin(tmp_path).stat().st_mode & 0o777 == 0o755
    assert (user_bin(tmp_path) / "chip").stat().st_mode & 0o777 == 0o755


def test_an_upgrade_replacement_is_not_tracked_so_rollback_keeps_the_binary(tmp_path):
    user_bin(tmp_path).mkdir(parents=True)
    (user_bin(tmp_path) / "chip").write_bytes(b"old")
    tracker = Tracker()
    machine = ChipMachine("0.0.60", user_bin(tmp_path) / "chip")
    t, downloads = make(tmp_path, machine, payload=b"new")
    assert tools.install_user_binaries(t, {"chip"}, tracker, upgrade=True)
    assert len(downloads) == 1
    assert (user_bin(tmp_path) / "chip").read_bytes() == b"new"
    assert tracker.entries == []


def test_the_upgrade_ignores_a_legacy_copy_when_there_is_no_user_level_binary(tmp_path, monkeypatch):
    legacy = tmp_path / "usr-local-bin"
    legacy.mkdir()
    (legacy / "chip").write_text("")
    monkeypatch.setattr("shutil.which", lambda name, path=None: str(legacy / "chip"))
    machine = ChipMachine("0.0.1", legacy / "chip")
    t, downloads = make(tmp_path, machine)
    ri.upgrade_user_binaries(t, {"chip"})
    assert downloads == []
    assert not machine.ran(str(legacy / "chip"))


def test_the_real_user_binaries_step_installs_under_no_system(tmp_path, monkeypatch):
    import dataclasses

    from dotfiles_setup import install_flow as flow

    def download(url, dest):
        dest.write_bytes(b"\x7fELF")

    base = flow.FlowInputs(
        t=None, dotfiles_dir=tmp_path / "repo", preset_name="work", packages=frozenset({"chip"}), overlay_root=None,
        force=False, stamp="T1", euid=1000, system="never",
    )
    home = tmp_path / "home"
    home.mkdir()
    t = tools.Tooling(Logger(dry_run=False, verbosity=1), home, run=Machine(), download=download)
    real = flow.build_steps
    monkeypatch.setattr(flow, "build_steps", lambda *a: [s for s in real(*a) if s[0] == "install_user_binaries"])
    monkeypatch.setattr(flow.SudoSession, "start", lambda self: pytest.fail("sudo must not be requested"))
    result = flow.run_install(dataclasses.replace(base, t=t))
    assert result.succeeded
    assert (home / ".local" / "bin" / "chip").is_file()


def test_the_real_user_binaries_step_fails_the_run_when_the_directory_cannot_be_made(tmp_path, monkeypatch):
    import dataclasses

    from dotfiles_setup import install_flow as flow

    base = flow.FlowInputs(
        t=None, dotfiles_dir=tmp_path / "repo", preset_name="work", packages=frozenset({"chip"}), overlay_root=None,
        force=False, stamp="T1", euid=1000, system="never",
    )
    home = tmp_path / "home"
    home.mkdir()
    (home / ".local").write_text("a file")
    t = tools.Tooling(Logger(dry_run=False, verbosity=1), home, run=Machine())
    real = flow.build_steps
    monkeypatch.setattr(flow, "build_steps", lambda *a: [s for s in real(*a) if s[0] == "install_user_binaries"])
    result = flow.run_install(dataclasses.replace(base, t=t))
    assert not result.succeeded
    assert result.rollback_pending


def test_upgrade_replaces_an_older_user_level_chip(tmp_path):
    user_bin(tmp_path).mkdir(parents=True)
    (user_bin(tmp_path) / "chip").write_bytes(b"old")
    machine = ChipMachine("0.0.60", user_bin(tmp_path) / "chip")
    t, downloads = make(tmp_path, machine, payload=b"new")
    ri.upgrade_user_binaries(t, {"chip"})
    assert downloads == [chip_url(ri.SPEC_DATA["chip"].version)]
    assert machine.ran("dpkg", "--compare-versions", "0.0.60", "lt", ri.SPEC_DATA["chip"].version)
    assert not machine.ran("sudo")


def test_upgrade_never_downgrades_a_user_level_chip(tmp_path):
    user_bin(tmp_path).mkdir(parents=True)
    (user_bin(tmp_path) / "chip").write_bytes(b"newer")
    machine = ChipMachine("9.9.9", user_bin(tmp_path) / "chip", fail=NOT_OLDER)
    t, downloads = make(tmp_path, machine)
    ri.upgrade_user_binaries(t, {"chip"})
    assert downloads == []
    assert (user_bin(tmp_path) / "chip").read_bytes() == b"newer"


def test_the_user_bin_install_step_upgrades_only_with_the_flag(tmp_path):
    user_bin(tmp_path).mkdir(parents=True)
    (user_bin(tmp_path) / "chip").write_bytes(b"old")
    machine = ChipMachine("0.0.60", user_bin(tmp_path) / "chip")
    t, downloads = make(tmp_path, machine, payload=b"new")
    assert tools.install_user_binaries(t, {"chip"}, Tracker())
    assert downloads == []
    assert tools.install_user_binaries(t, {"chip"}, Tracker(), upgrade=True)
    assert len(downloads) == 1


def aws_root(tmp_path):
    return tmp_path / ".local" / "aws-cli"


def test_istioctl_is_tracked_like_the_other_binary_specs(tmp_path):
    tracker = Tracker()
    version = ri.SPEC_DATA["istioctl"].version
    t, _ = make(tmp_path, Machine(), payload=tarball(f"istio-{version}/bin/istioctl"))
    ri.install_user_binaries(t, {"istioctl"}, tracker)
    assert tracker.entries == [
        f"DIR_CREATED:{user_bin(tmp_path)}",
        f"BIN_INSTALLED:{user_bin(tmp_path) / 'istioctl'}|{digest_of(b'bin')}",
    ]


def test_istioctl_counts_as_installed_only_inside_the_user_bin_dir(tmp_path, monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name, path=None: f"/usr/local/bin/{name}")
    t, downloads = make(tmp_path, Machine(), payload=tarball("istioctl"))
    ri.install_user_binaries(t, {"istioctl"}, Tracker())
    assert len(downloads) == 1


def test_awscli_counts_as_installed_only_inside_the_user_bin_dir(tmp_path, monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name, path=None: f"/usr/local/bin/{name}")
    machine = Machine()
    t, downloads = make(tmp_path, machine, payload=zipball("aws/install", 0o755))
    ri.install_user_binaries(t, {"awscli"}, Tracker())
    assert len(downloads) == 1
    user_bin(tmp_path).joinpath("aws").write_text("")
    ri.install_user_binaries(t, {"awscli"}, Tracker())
    assert len(downloads) == 1


class AwsMachine(Machine):
    """Plays the AWS installer: builds the tree under -i and links `links` into -b, exiting 0 either way."""

    def __init__(self, links=("aws", "aws_completer"), tree=("v2", "current"), **kwargs):
        super().__init__(**kwargs)
        self.links, self.tree = tuple(links), tuple(tree)

    def __call__(self, argv, **kwargs):
        if argv[0].endswith("aws/install"):
            root, bin_dir = Path(argv[argv.index("-i") + 1]), Path(argv[argv.index("-b") + 1])
            self.build(root, bin_dir)
        return super().__call__(argv, **kwargs)

    def build(self, root, bin_dir):
        if self.tree:
            version_dir = root.joinpath(*self.tree)
            (version_dir / "bin").mkdir(parents=True, exist_ok=True)
            for name in ("aws", "aws_completer"):
                (version_dir / "bin" / name).write_text("#!/bin/sh\n")
        for name in self.links:
            link = bin_dir / name
            link.unlink(missing_ok=True)
            link.symlink_to(root / "v2" / "current" / "bin" / name)


def test_a_missing_aws_link_is_restored_when_the_installer_exits_zero(tmp_path):
    tracker = Tracker()
    t, _ = make(tmp_path, AwsMachine(links=()), payload=zipball("aws/install", 0o755))
    ri.install_user_binaries(t, {"awscli"}, tracker)
    link = user_bin(tmp_path) / "aws"
    assert link.is_symlink()
    assert link.resolve() == (aws_root(tmp_path) / "v2" / "current" / "bin" / "aws").resolve()
    assert f"TREE_INSTALLED:{aws_root(tmp_path)}|{link}" in tracker.entries


def test_the_aws_link_falls_back_to_the_versioned_directory(tmp_path):
    t, _ = make(tmp_path, AwsMachine(links=(), tree=("v2", "2.39.6")), payload=zipball("aws/install", 0o755))
    ri.install_user_binaries(t, {"awscli"}, Tracker())
    link = user_bin(tmp_path) / "aws"
    assert link.resolve() == (aws_root(tmp_path) / "v2" / "2.39.6" / "bin" / "aws").resolve()


def test_an_aws_link_that_cannot_be_restored_fails_the_step(tmp_path, capsys):
    tracker = Tracker()
    t, _ = make(tmp_path, AwsMachine(links=(), tree=()), payload=zipball("aws/install", 0o755))
    ri.install_user_binaries(t, {"awscli"}, tracker)
    output = capsys.readouterr()
    assert not (user_bin(tmp_path) / "aws").exists()
    assert "installer left no aws executable" in output.err
    assert "Failed to install AWS CLI" in output.err
    assert [e.split(":")[0] for e in tracker.entries] == ["DIR_CREATED"]


def test_an_aws_link_the_installer_made_is_left_alone(tmp_path):
    t, _ = make(tmp_path, AwsMachine(), payload=zipball("aws/install", 0o755))
    ri.install_user_binaries(t, {"awscli"}, Tracker())
    assert (user_bin(tmp_path) / "aws").readlink() == aws_root(tmp_path) / "v2" / "current" / "bin" / "aws"


def test_a_preexisting_completer_link_is_not_tracked(tmp_path):
    user_bin(tmp_path).mkdir(parents=True)
    (user_bin(tmp_path) / "aws_completer").symlink_to(tmp_path / "elsewhere")
    tracker = Tracker()
    t, _ = make(tmp_path, AwsMachine(links=("aws",)), payload=zipball("aws/install", 0o755))
    ri.install_user_binaries(t, {"awscli"}, tracker)
    assert not any("aws_completer" in e for e in tracker.entries)
    assert any(e.startswith("TREE_INSTALLED") for e in tracker.entries)


def test_a_new_completer_link_is_tracked(tmp_path):
    tracker = Tracker()
    t, _ = make(tmp_path, AwsMachine(), payload=zipball("aws/install", 0o755))
    ri.install_user_binaries(t, {"awscli"}, tracker)
    assert f"LINK_INSTALLED:{aws_root(tmp_path)}|{user_bin(tmp_path) / 'aws_completer'}" in tracker.entries


def test_a_completer_the_installer_did_not_create_is_not_tracked(tmp_path):
    tracker = Tracker()
    t, _ = make(tmp_path, AwsMachine(links=("aws",)), payload=zipball("aws/install", 0o755))
    ri.install_user_binaries(t, {"awscli"}, tracker)
    assert not any("aws_completer" in e for e in tracker.entries)


def test_a_fresh_awscli_install_tracks_its_tree_and_link(tmp_path):
    tracker = Tracker()
    t, _ = make(tmp_path, AwsMachine(), payload=zipball("aws/install", 0o755))
    ri.install_user_binaries(t, {"awscli"}, tracker)
    assert tracker.entries == [
        f"DIR_CREATED:{user_bin(tmp_path)}",
        f"TREE_INSTALLED:{aws_root(tmp_path)}|{user_bin(tmp_path) / 'aws'}",
        f"LINK_INSTALLED:{aws_root(tmp_path)}|{user_bin(tmp_path) / 'aws_completer'}",
    ]


def test_awscli_over_an_existing_tree_tracks_only_the_link(tmp_path):
    aws_root(tmp_path).mkdir(parents=True)
    user_bin(tmp_path).mkdir(parents=True)
    tracker = Tracker()
    t, _ = make(tmp_path, AwsMachine(), payload=zipball("aws/install", 0o755))
    ri.install_user_binaries(t, {"awscli"}, tracker)
    assert tracker.entries == [
        f"LINK_INSTALLED:{aws_root(tmp_path)}|{user_bin(tmp_path) / 'aws'}",
        f"LINK_INSTALLED:{aws_root(tmp_path)}|{user_bin(tmp_path) / 'aws_completer'}",
    ]


def test_a_failed_awscli_installer_is_not_tracked(tmp_path):
    tracker = Tracker()
    t, _ = make(tmp_path, Machine(), payload=b"not a zip")
    ri.install_user_binaries(t, {"awscli"}, tracker)
    assert [e.split(":")[0] for e in tracker.entries] == ["DIR_CREATED"]


def test_upgrade_does_not_touch_istioctl_or_awscli(tmp_path):
    user_bin(tmp_path).mkdir(parents=True)
    for name in ("istioctl", "aws"):
        (user_bin(tmp_path) / name).write_text("old")
    t, downloads = make(tmp_path, Machine())
    assert tools.install_user_binaries(t, {"istioctl", "awscli"}, Tracker(), upgrade=True)
    assert downloads == []
