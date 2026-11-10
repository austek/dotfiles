from types import SimpleNamespace

import pytest
from cli_support import _plan_for, _prior, _write_optouts
from dotfiles_setup import apt_packages, optouts, package_sets
from dotfiles_setup.backends.apt import AptBackend
from dotfiles_setup.log import Logger
from dotfiles_setup.plan import combine_package_names
from dotfiles_setup.rollback import RollbackLog
from dotfiles_setup.system_steps import SystemContext
from dotfiles_setup.tooling import Tooling


def test_combine_package_names_resolves_overrides_and_merges_overlay(tmp_path):
    backend = AptBackend(dotfiles_dir=tmp_path, backend_overrides={"bat": "batcat"})
    assert combine_package_names(backend, ("bat", "git"), ("zsh", "git")) == ("batcat", "git", "zsh")


def test_rule001_wanted_is_preset_files_plus_overlay_extras_minus_optouts(tmp_path):
    backend = AptBackend(dotfiles_dir=tmp_path, backend_overrides={"bat": "batcat"})
    combined = combine_package_names(backend, ("git", "curl", "github:foo/bar", "bat"), ("htop",))
    wanted = package_sets.wanted(combined, frozenset({"curl", "batcat"}), backend.resolve_name)
    assert wanted == frozenset({"git", "github:foo/bar", "htop"})


def test_an_opted_out_overlay_name_is_resolved_like_a_preset_name(tmp_path):
    backend = AptBackend(dotfiles_dir=tmp_path, backend_overrides={"batcat": "bat"})
    combined = combine_package_names(backend, (), ("batcat",))
    assert combined == ("bat",)
    assert package_sets.wanted(combined, frozenset({"batcat"}), backend.resolve_name) == frozenset()


def test_plan_excludes_optouts_from_wanted(isolated_dotfiles):
    _dotfiles_dir, tmp_path = isolated_dotfiles
    _write_optouts(tmp_path, f"{optouts.HEADER}\ncurl\n")
    assert _plan_for(tmp_path).wanted == frozenset({"zsh"})


def _write_pins(tmp_path):
    packages = tmp_path / "dotfiles" / "packages"
    packages.mkdir(parents=True, exist_ok=True)
    (packages / "github_bins.txt").write_text("derailed/k9s 0.51.0 k9s_linux_amd64.deb\n")


def test_plan_includes_pin_entries_in_combined(isolated_dotfiles):
    _dotfiles_dir, tmp_path = isolated_dotfiles
    _write_pins(tmp_path)
    plan = _plan_for(tmp_path)
    assert "github:derailed/k9s" in plan.combined
    assert "github:derailed/k9s" in plan.wanted


def test_optout_of_pin_skips_install_and_removes_it(isolated_dotfiles):
    _dotfiles_dir, tmp_path = isolated_dotfiles
    _write_pins(tmp_path)
    _write_optouts(tmp_path, f"{optouts.HEADER}\ngithub:derailed/k9s\n")
    plan = _plan_for(tmp_path, _prior("homelab", ("curl", "github:derailed/k9s", "zsh")))
    assert "github:derailed/k9s" not in plan.wanted
    assert plan.pending == ("github:derailed/k9s",)
    ctx = SystemContext(
        Tooling(Logger(dry_run=False), tmp_path), plan.dotfiles_dir, plan.wanted, RollbackLog(tmp_path / "log"),
    )
    assert apt_packages.pending_github_bins(ctx) == []


def test_migration_does_not_opt_out_pins(isolated_dotfiles):
    _dotfiles_dir, tmp_path = isolated_dotfiles
    _write_pins(tmp_path)
    _write_optouts(tmp_path, "zsh\ncurl\n")
    plan = _plan_for(tmp_path)
    assert "github:derailed/k9s" not in plan.loaded.names
    assert "github:derailed/k9s" in plan.wanted
    no_dpkg = Tooling(Logger(dry_run=False), tmp_path, run=lambda *a, **k: SimpleNamespace(returncode=0, stdout=""))
    ctx = SystemContext(no_dpkg, plan.dotfiles_dir, plan.wanted, RollbackLog(tmp_path / "log"))
    assert apt_packages.pending_github_bins(ctx) == ["k9s_linux_amd64.deb"]


def test_a_pin_moved_to_apt_is_kept_and_not_pending(isolated_dotfiles, capsys):
    _dotfiles_dir, tmp_path = isolated_dotfiles
    plan = _plan_for(tmp_path, _prior("homelab", ("curl", "github:derailed/k9s", "zsh")), names=("zsh", "curl", "k9s"))
    assert plan.pending == ()
    assert "github:derailed/k9s moved to another manager; keeping k9s" in capsys.readouterr().out


def test_an_apt_package_moved_to_a_pin_is_kept_and_not_pending(isolated_dotfiles):
    _dotfiles_dir, tmp_path = isolated_dotfiles
    _write_pins(tmp_path)
    assert _plan_for(tmp_path, _prior("homelab", ("curl", "k9s", "zsh"))).pending == ()


def test_plan_without_an_optout_file_wants_everything_and_creates_nothing(isolated_dotfiles):
    _dotfiles_dir, tmp_path = isolated_dotfiles
    assert _plan_for(tmp_path).wanted == frozenset({"zsh", "curl"})
    assert not (tmp_path / "state" / "packages").exists()


def test_plan_reads_a_header_below_a_comment_as_optouts(isolated_dotfiles):
    _dotfiles_dir, tmp_path = isolated_dotfiles
    text = f"# mine\n{optouts.HEADER}\ncurl\n"
    package_file = _write_optouts(tmp_path, text)
    assert _plan_for(tmp_path).wanted == frozenset({"zsh"})
    assert package_file.read_text() == text


def test_plan_reads_a_headerless_file_as_optouts_once_migrated(isolated_dotfiles, capsys):
    _dotfiles_dir, tmp_path = isolated_dotfiles
    package_file = _write_optouts(tmp_path, "curl\n")
    prior = _prior("homelab", ("curl", "zsh"), optouts_migrated=True)
    assert _plan_for(tmp_path, prior).wanted == frozenset({"zsh"})
    assert package_file.read_text() == "curl\n"
    assert "no header" in capsys.readouterr().out


def test_plan_migrates_a_headerless_fork_on_an_unmigrated_machine(isolated_dotfiles):
    _dotfiles_dir, tmp_path = isolated_dotfiles
    _write_optouts(tmp_path, "zsh\n")
    assert _plan_for(tmp_path, _prior("homelab", ("zsh",))).wanted == frozenset({"zsh"})


def test_migration_optouts_are_not_pending(isolated_dotfiles):
    _dotfiles_dir, tmp_path = isolated_dotfiles
    _write_optouts(tmp_path, "zsh\n")
    assert _plan_for(tmp_path, _prior("homelab", ("curl", "zsh"))).pending == ()


def test_rule008_missing_overlay_skips_all_removals(isolated_dotfiles, capsys):
    _dotfiles_dir, tmp_path = isolated_dotfiles
    prior = _prior("homelab", ("curl", "extra", "zsh"), overlay_root=str(tmp_path / "private"))
    assert _plan_for(tmp_path, prior).pending == ()
    assert "overlay not found: skipping removals" in capsys.readouterr().out.lower()


def test_overlay_at_a_new_path_keeps_removals(isolated_dotfiles, capsys):
    _dotfiles_dir, tmp_path = isolated_dotfiles
    prior = _prior("homelab", ("curl", "extra", "zsh"), overlay_root=str(tmp_path / "private"))
    assert _plan_for(tmp_path, prior, overlay_root=tmp_path / "elsewhere").pending == ("extra",)
    assert "overlay not found" not in capsys.readouterr().out.lower()


def test_same_overlay_keeps_removals(isolated_dotfiles):
    _dotfiles_dir, tmp_path = isolated_dotfiles
    prior = _prior("homelab", ("curl", "extra", "zsh"), overlay_root=str(tmp_path / "private"))
    assert _plan_for(tmp_path, prior, overlay_root=tmp_path / "private").pending == ("extra",)


def test_rule002_plan_pending_lists_dropped_packages(isolated_dotfiles):
    _dotfiles_dir, tmp_path = isolated_dotfiles
    plan = _plan_for(tmp_path, _prior("homelab", ("curl", "htop", "zsh")))
    assert plan.pending == ("htop",)


def test_rule002_pending_drops_a_pin_whose_dpkg_name_is_still_wanted(isolated_dotfiles):
    _dotfiles_dir, tmp_path = isolated_dotfiles
    prior = _prior("homelab", ("a", "b", "github:u/b2", "c"))
    plan = _plan_for(tmp_path, prior, names=("a", "b2"))
    assert plan.pending == ("b", "c")


def test_rule002_no_applied_list_means_nothing_is_pending(isolated_dotfiles):
    _dotfiles_dir, tmp_path = isolated_dotfiles
    assert _plan_for(tmp_path, None).pending == ()


def test_rule002_plan_ignores_applied_for_other_preset(isolated_dotfiles):
    _dotfiles_dir, tmp_path = isolated_dotfiles
    plan = _plan_for(tmp_path, _prior("work", ("htop",)))
    assert plan.pending == ()


def test_plan_leaves_other_presets_files_in_place(isolated_dotfiles, capsys):
    _dotfiles_dir, tmp_path = isolated_dotfiles
    other = _write_optouts(tmp_path, "vim\n", name="work.txt")
    _plan_for(tmp_path)
    assert other.exists()
    assert "Will move" in capsys.readouterr().out


def test_dry_run_plan_moves_no_other_presets_file(isolated_dotfiles, capsys):
    _dotfiles_dir, tmp_path = isolated_dotfiles
    other = _write_optouts(tmp_path, "vim\n", name="work.txt")
    _plan_for(tmp_path, dry_run=True)
    assert other.exists()
    assert "Would move" in capsys.readouterr().out


@pytest.mark.parametrize(("applied", "pending"), [(("zsh",), ()), (("curl", "zsh"), ("curl",))])
def test_a_headered_optout_is_pending_only_when_it_was_applied(isolated_dotfiles, applied, pending):
    _dotfiles_dir, tmp_path = isolated_dotfiles
    _write_optouts(tmp_path, f"{optouts.HEADER}\ncurl\n")
    assert _plan_for(tmp_path, _prior("homelab", applied, optouts_migrated=True)).pending == pending


def test_without_state_or_a_legacy_file_nothing_is_pending(isolated_dotfiles):
    _dotfiles_dir, tmp_path = isolated_dotfiles
    assert _plan_for(tmp_path).pending == ()


def test_optout_for_unlisted_package_warns_only(isolated_dotfiles, capsys):
    _dotfiles_dir, tmp_path = isolated_dotfiles
    _write_optouts(tmp_path, f"{optouts.HEADER}\nghost\n")
    assert _plan_for(tmp_path).wanted == frozenset({"zsh", "curl"})
    assert "ghost" in capsys.readouterr().out


def test_migration_messages_show_at_default_verbosity(isolated_dotfiles, capsys):
    _dotfiles_dir, tmp_path = isolated_dotfiles
    _write_optouts(tmp_path, "zsh\nextra\n")
    _write_optouts(tmp_path, "vim\n", name="work.txt")
    _plan_for(tmp_path)
    out = capsys.readouterr().out
    assert "Will migrate" in out
    assert "work.txt" in out
    assert "only in the old file: extra" in out
