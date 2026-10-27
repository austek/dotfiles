import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest
from dotfiles_setup import apt_packages as ap
from dotfiles_setup import (
    checksums,
    claude_tools,
    post_apt_installers,
    system_steps,
    tools,
)
from dotfiles_setup import vendor_installers as vi
from dotfiles_setup.log import Logger
from dotfiles_setup.rollback import RollbackLog

ROOT = Path(__file__).resolve().parent.parent
PAYLOAD = b"payload"
DIGEST = hashlib.sha256(PAYLOAD).hexdigest()
DEB_URL = "https://github.com/owner/tool/releases/download/v1.2.3/tool_1.2.3_amd64.deb"
BINS = "owner/tool 1.2.3 tool_1.2.3_amd64.deb\n"


class Machine:
    def __init__(self):
        self.commands = []

    def __call__(self, argv, **kwargs):
        self.commands.append(list(argv))
        return SimpleNamespace(returncode=0, stdout="", stderr="")


@pytest.fixture(autouse=True)
def isolated_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.setattr("shutil.which", lambda name: None)


def tooling(tmp_path, machine, table):
    def download(url, dest):
        dest.write_bytes(PAYLOAD)

    return tools.Tooling(
        Logger(dry_run=False, verbosity=1), tmp_path, run=machine, download=download,
        fetch=lambda url: PAYLOAD.decode(), checksums=table,
    )


def test_load_reads_digest_and_url_pairs_and_skips_comments(tmp_path):
    listing = tmp_path / "checksums.txt"
    listing.write_text(f"# header\n\n{DIGEST}  https://x/a.deb  # note\nnot-a-digest  https://x/b\n")
    assert checksums.load(listing) == {"https://x/a.deb": DIGEST}


def test_a_missing_listing_loads_as_an_empty_table(tmp_path):
    assert checksums.load(tmp_path / "absent.txt") == {}


def test_matching_content_passes_and_none_disables_the_check():
    checksums.verify({"u": DIGEST}, "u", PAYLOAD)
    checksums.verify(None, "u", b"anything")


def test_a_mismatch_names_the_url_and_both_digests():
    with pytest.raises(checksums.ChecksumError, match=f"digest mismatch for u: expected {DIGEST}, got "):
        checksums.verify({"u": DIGEST}, "u", b"tampered")


def test_a_url_without_a_digest_is_refused_and_named():
    with pytest.raises(checksums.ChecksumError, match="no digest recorded for https://x/new.deb"):
        checksums.verify({}, "https://x/new.deb", PAYLOAD)


def bins_context(tmp_path, machine, table):
    repo = tmp_path / "repo"
    (repo / "packages").mkdir(parents=True)
    (repo / "packages" / "github_bins.txt").write_text(BINS)
    return system_steps.SystemContext(
        tooling(tmp_path, machine, table), repo, frozenset(), RollbackLog(tmp_path / "rollback.log"),
    )


def test_a_deb_with_the_recorded_digest_is_installed(tmp_path):
    machine = Machine()
    ap.install_github_bins(bins_context(tmp_path, machine, {DEB_URL: DIGEST}))
    assert any(c[:3] == ["sudo", "dpkg", "-i"] for c in machine.commands)


def test_a_deb_that_differs_from_its_digest_is_not_installed(tmp_path, capsys):
    machine = Machine()
    ap.install_github_bins(bins_context(tmp_path, machine, {DEB_URL: "0" * 64}))
    assert not any(c[:3] == ["sudo", "dpkg", "-i"] for c in machine.commands)
    assert f"digest mismatch for {DEB_URL}" in capsys.readouterr().err


def test_a_deb_without_a_digest_is_not_installed_and_the_entry_is_named(tmp_path, capsys):
    machine = Machine()
    ap.install_github_bins(bins_context(tmp_path, machine, {}))
    assert not any(c[:3] == ["sudo", "dpkg", "-i"] for c in machine.commands)
    assert f"no digest recorded for {DEB_URL}" in capsys.readouterr().err


def test_a_refused_deb_is_not_cached_for_the_next_run(tmp_path):
    ap.install_github_bins(bins_context(tmp_path, Machine(), {DEB_URL: "0" * 64}))
    assert not list((tmp_path / "cache").rglob("*.deb"))


def test_a_vendor_script_that_differs_from_its_digest_never_runs(tmp_path, capsys):
    machine = Machine()
    t = tooling(tmp_path, machine, {vi.UV.url: "0" * 64})
    assert vi.install_vendor(t, vi.UV) is None
    assert machine.commands == []
    assert f"digest mismatch for {vi.UV.url}" in capsys.readouterr().err


def test_a_vendor_script_with_the_recorded_digest_runs(tmp_path):
    machine = Machine()
    vi.install_vendor(tooling(tmp_path, machine, {vi.UV.url: DIGEST}), vi.UV)
    assert machine.commands[0][0] == "sh"


def test_a_fetched_installer_script_that_differs_from_its_digest_never_runs(tmp_path, capsys):
    machine = Machine()
    t = tooling(tmp_path, machine, {tools.SDKMAN_URL: "0" * 64})
    assert tools.install_sdkman(t) is False
    assert machine.commands == []
    assert f"digest mismatch for {tools.SDKMAN_URL}" in capsys.readouterr().err


def test_every_pinned_github_bin_has_a_recorded_digest():
    table = checksums.load(ROOT / "packages" / checksums.FILE_NAME)
    missing = []
    for _, repo, version, filename in ap._bin_entries(ROOT / "packages" / "github_bins.txt"):
        url = f"https://github.com/{repo}/releases/download/v{version}/{filename}"
        if url not in table:
            missing.append(f"{repo} {version} {filename}")
    assert not missing, f"record a digest in packages/checksums.txt for: {missing}"


@pytest.mark.parametrize("url", [
    vi.CODERABBIT.url, vi.SONARQUBE_CLI.url, vi.UV.url, claude_tools.RTK_INSTALL_URL,
    post_apt_installers.RUSTUP_INIT_URL, tools.SDKMAN_URL, tools.OMZ_URL, tools.NVM_FALLBACK_URL,
])
def test_every_vendor_installer_script_has_a_recorded_digest(url):
    assert url in checksums.load(ROOT / "packages" / checksums.FILE_NAME)
