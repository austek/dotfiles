import re

import pytest
from dotfiles_setup import release_installers as ri
from dotfiles_setup import stale_copies, tools
from dotfiles_setup.log import Logger


@pytest.fixture
def system_dir(tmp_path, monkeypatch):
    path = tmp_path / "usr-local-bin"
    path.mkdir()
    monkeypatch.setattr(ri, "SYSTEM_BIN_DIR", path)
    monkeypatch.setenv("PATH", f"{path}:/usr/bin")
    return path


def tooling(tmp_path):
    return tools.Tooling(Logger(dry_run=False, verbosity=1), tmp_path)


def put(directory, name, content="x", mode=0o755):
    directory.mkdir(parents=True, exist_ok=True)
    (directory / name).write_text(content)
    (directory / name).chmod(mode)
    return directory / name


def lines(capsys):
    """Message text of each info line, without color codes or the level tag."""
    raw = capsys.readouterr().out.splitlines()
    plain = [re.sub(r"\x1b\[[0-9;]*m", "", line) for line in raw]
    return [line.removeprefix("[INFO] ") for line in plain if line.strip()]


def test_a_system_copy_is_reported_as_shadowed_and_kept(tmp_path, system_dir, capsys):
    managed = put(tmp_path / ".local/bin", "sops", "new")
    legacy = put(system_dir, "sops", "old")
    stale_copies.report_stale_copies(tooling(tmp_path), ["sops"])
    assert lines(capsys) == [f"{legacy} is now shadowed by {managed}; remove it with sudo when convenient."]
    assert legacy.read_text() == "old"


@pytest.mark.parametrize("spelling", ["{dir}/", "{dir}//", "{dir}/./"])
def test_a_system_dir_on_path_with_another_spelling_still_counts_as_on_path(tmp_path, system_dir, capsys, monkeypatch, spelling):
    monkeypatch.setenv("PATH", f"{spelling.format(dir=system_dir)}:/usr/bin")
    managed = put(tmp_path / ".local/bin", "sops", "new")
    legacy = put(system_dir, "sops", "old")
    stale_copies.report_stale_copies(tooling(tmp_path), ["sops"])
    assert lines(capsys) == [f"{legacy} is now shadowed by {managed}; remove it with sudo when convenient."]


def test_a_system_copy_is_described_neutrally_when_its_directory_is_not_on_path(tmp_path, system_dir, capsys, monkeypatch):
    monkeypatch.setenv("PATH", "/usr/bin")
    put(tmp_path / ".local/bin", "sops", "new")
    legacy = put(system_dir, "sops", "old")
    stale_copies.report_stale_copies(tooling(tmp_path), ["sops"])
    assert lines(capsys) == [f"{legacy} also exists; it is not on PATH here."]


def test_a_shadowing_copy_is_left_to_the_doctor_check_and_kept(tmp_path, system_dir, capsys, monkeypatch):
    monkeypatch.setenv("PATH", "/usr/bin")
    managed = put(tmp_path / ".local/bin", "sops", "new")
    stale = put(tmp_path / "bin", "sops", "old")
    stale_copies.report_stale_copies(tooling(tmp_path), ["sops"])
    assert lines(capsys) == []
    assert stale_copies.shadowing_copies(tooling(tmp_path), ["sops"]) == ((stale, managed),)
    assert stale.read_text() == "old"


@pytest.mark.parametrize("directory", ["bin", ".dotfiles/bin"])
def test_a_copy_that_precedes_the_user_bin_dir_is_a_shadowing_copy(tmp_path, system_dir, directory):
    managed = put(tmp_path / ".local/bin", "sops", "new")
    stale = put(tmp_path / directory, "sops", "old")
    assert stale_copies.shadowing_copies(tooling(tmp_path), ["sops"]) == ((stale, managed),)


def test_a_copy_after_the_user_bin_dir_is_not_a_shadowing_copy(tmp_path, system_dir):
    put(tmp_path / ".local/bin", "sops", "new")
    put(system_dir, "sops", "old")
    assert stale_copies.shadowing_copies(tooling(tmp_path), ["sops"]) == ()


def test_only_the_copies_that_do_not_shadow_get_a_line(tmp_path, system_dir, capsys):
    put(tmp_path / ".local/bin", "sops")
    for directory in (system_dir, tmp_path / "bin", tmp_path / ".dotfiles/bin"):
        put(directory, "sops", "other")
    stale_copies.report_stale_copies(tooling(tmp_path), ["sops"])
    assert len(lines(capsys)) == 1
    assert len(stale_copies.shadowing_copies(tooling(tmp_path), ["sops"])) == 2


def test_a_non_executable_managed_binary_is_not_a_managed_copy(tmp_path, system_dir, capsys):
    put(tmp_path / ".local/bin", "sops", mode=0o644)
    put(system_dir, "sops", "old")
    stale_copies.report_stale_copies(tooling(tmp_path), ["sops"])
    assert lines(capsys) == []


def test_a_missing_managed_binary_reports_nothing(tmp_path, system_dir, capsys):
    put(system_dir, "sops")
    stale_copies.report_stale_copies(tooling(tmp_path), ["sops"])
    assert lines(capsys) == []


def test_a_name_that_is_not_asked_about_is_not_checked(tmp_path, system_dir, capsys):
    put(tmp_path / ".local/bin", "sops")
    put(system_dir, "sops", "other")
    stale_copies.report_stale_copies(tooling(tmp_path), ["helm"])
    assert lines(capsys) == []


def test_a_copy_symlinked_to_the_managed_file_is_skipped(tmp_path, system_dir, capsys):
    managed = put(tmp_path / ".local/bin", "sops")
    (system_dir / "sops").symlink_to(managed)
    (tmp_path / "bin").mkdir()
    (tmp_path / "bin" / "sops").symlink_to(managed)
    stale_copies.report_stale_copies(tooling(tmp_path), ["sops"])
    assert lines(capsys) == []


def test_a_managed_symlink_to_the_copy_is_skipped(tmp_path, system_dir, capsys):
    real = put(tmp_path / "bin", "sops")
    (tmp_path / ".local/bin").mkdir(parents=True)
    (tmp_path / ".local/bin/sops").symlink_to(real)
    stale_copies.report_stale_copies(tooling(tmp_path), ["sops"])
    assert lines(capsys) == []


def test_a_directory_or_broken_symlink_under_the_name_is_skipped(tmp_path, system_dir, capsys):
    put(tmp_path / ".local/bin", "sops")
    (system_dir / "sops").mkdir()
    (tmp_path / "bin").mkdir()
    (tmp_path / "bin" / "sops").symlink_to(tmp_path / "gone")
    stale_copies.report_stale_copies(tooling(tmp_path), ["sops"])
    assert lines(capsys) == []
    assert (system_dir / "sops").is_dir()


def test_a_symlink_to_a_different_file_counts_as_a_copy(tmp_path, system_dir, capsys):
    put(tmp_path / ".local/bin", "sops", "new")
    other = put(tmp_path / "elsewhere", "sops-real", "old")
    (system_dir / "sops").symlink_to(other)
    stale_copies.report_stale_copies(tooling(tmp_path), ["sops"])
    assert len(lines(capsys)) == 1


def test_a_legacy_istioctl_and_aws_in_the_system_dir_are_reported_and_kept(tmp_path, system_dir, capsys):
    names = stale_copies.managed_names({"istioctl", "awscli"})
    for name in ("istioctl", "aws"):
        put(tmp_path / ".local/bin", name, "new")
        put(system_dir, name, "old")
    stale_copies.report_stale_copies(tooling(tmp_path), names)
    assert [line.split(" is now")[0] for line in lines(capsys)] == [str(system_dir / "aws"), str(system_dir / "istioctl")]
    assert (system_dir / "aws").read_text() == "old"


def test_the_search_order_matches_the_shell_path_order(tmp_path, system_dir):
    assert stale_copies.search_dirs(tooling(tmp_path)) == (
        tmp_path / ".dotfiles/bin", tmp_path / "bin", tmp_path / ".local/bin", system_dir,
    )


def test_the_managed_names_cover_release_binaries_links_and_vendor_tools():
    names = stale_copies.managed_names({
        "sops", "istioctl", "awscli", "jetbrains-toolbox", "sonarqube-cli", "uv", "ruff", "auditr", "cargo-deny",
        "cargo-audit", "coderabbit",
    })
    assert names == {
        "sops", "istioctl", "aws", "jetbrains-toolbox", "sonar", "uv", "ruff", "auditr", "cargo-deny", "cargo-audit",
        "coderabbit", "rtk",
    }


def test_unwanted_packages_add_no_names_beyond_the_always_managed_ones():
    assert stale_copies.managed_names({"vim"}) == {"rtk"}


def test_a_package_without_a_user_level_binary_adds_no_name():
    assert stale_copies.managed_names({"zoom"}) == {"rtk"}
