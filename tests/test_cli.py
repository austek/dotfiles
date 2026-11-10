import io
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from dotfiles_setup import (
    apt_packages,
    optouts,
    overlay,
    package_sets,
    settings_drift,
    state,
)
from dotfiles_setup.backends import InstallResult
from dotfiles_setup.backends.apt import AptBackend
from dotfiles_setup.approval import applied_after_removals, confirm_removals
from dotfiles_setup.claude_settings import _replace_settings_target
from dotfiles_setup.cli import Env, build_arg_parser, main
from dotfiles_setup.install_cmd import PERSIST_FAILED_EXIT_CODE
from dotfiles_setup.plan import _plan, combine_package_names
from dotfiles_setup.log import Logger
from dotfiles_setup.presets import Preset
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


def test_preset_is_optional_at_parse_time():
    args = build_arg_parser().parse_args(["install"])
    assert args.preset is None


def test_preset_accepts_any_value_at_parse_time():
    """Preset existence is validated by presets.load_preset(), not argparse —
    an unknown name here is a runtime FileNotFoundError, not a parse error."""
    parser = build_arg_parser()
    args = parser.parse_args(["install", "--preset", "bogus"])
    assert args.preset == "bogus"


@pytest.mark.parametrize("preset", ["work", "personal", "homelab"])
def test_preset_accepts_valid_values(preset):
    parser = build_arg_parser()
    args = parser.parse_args(["install", "--preset", preset])
    assert args.preset == preset


@pytest.mark.parametrize(("flags", "expected"), [([], False), (["--dry-run"], True)])
def test_dry_run_flag(flags, expected):
    args = build_arg_parser().parse_args(["install", "--preset", "work", *flags])
    assert args.dry_run is expected


@pytest.mark.parametrize(
    ("flags", "expected"),
    [([], 0), (["-v"], 1), (["-vv"], 2), (["-vvv"], 3)],
)
def test_verbosity_flag(flags, expected):
    args = build_arg_parser().parse_args(["install", "--preset", "work", *flags])
    assert args.verbosity == expected


def test_verbosity_accumulates_across_distinct_flags():
    parser = build_arg_parser()
    args = parser.parse_args(["install", "--preset", "work", "-v", "-vv"])
    assert args.verbosity == 3


def test_main_returns_zero_for_valid_preset(isolated_dotfiles):
    assert main(["install", "--preset", "homelab"]) == 0


def test_main_prints_dry_run_banner_when_requested(isolated_dotfiles, capsys):
    main(["install", "--preset", "homelab", "--dry-run"])
    assert "DRY-RUN MODE" in capsys.readouterr().out


def test_main_does_not_print_dry_run_banner_otherwise(isolated_dotfiles, capsys):
    main(["install", "--preset", "homelab"])
    assert "DRY-RUN MODE" not in capsys.readouterr().out


def test_main_without_command_prints_help_and_returns_1(capsys):
    assert main([]) == 1
    out = capsys.readouterr().out
    assert "usage:" in out
    assert "install" in out


def test_top_level_help_lists_install_subcommand_and_examples(capsys):
    parser = build_arg_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["-h"])
    out = capsys.readouterr().out
    assert "install" in out
    assert "Examples:" in out
    assert "dotfiles-setup install --preset work" in out


@pytest.fixture
def plugin_updates(monkeypatch):
    calls = []
    monkeypatch.setattr("dotfiles_setup.claude_plugins.update_claude_plugins", lambda logger, settings: calls.append(logger))
    return calls


@pytest.fixture
def foothold_syncs(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "dotfiles_setup.foothold.sync_footholds",
        lambda logger, wanted: calls.append(wanted),
    )
    return calls


def stub_subprocess(monkeypatch, returncode=0, stdout="installed", stderr="", calls=None):
    calls = [] if calls is None else calls

    def run(argv, **kwargs):
        calls.append(argv)
        return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)

    monkeypatch.setattr("dotfiles_setup.tooling.subprocess.run", run)
    return calls


@pytest.fixture
def flow_calls(monkeypatch):
    """Replaces the real install steps (sudo, apt, stow) with a recorder that succeeds."""
    calls = []

    def run_install(inputs):
        calls.append(inputs)
        return InstallResult(True, 0, "")

    monkeypatch.setattr("dotfiles_setup.install_flow.run_install", run_install)
    return calls


@pytest.fixture
def isolated_dotfiles(tmp_path, monkeypatch, flow_calls, plugin_updates, foothold_syncs):
    """A minimal fake dotfiles_dir with one preset + its package files, plus
    state/overlay redirected into tmp_path so tests never touch the real
    machine's ~/.config/dotfiles or ~/.dotfiles-private."""
    dotfiles_dir = tmp_path / "dotfiles"
    (dotfiles_dir / "presets").mkdir(parents=True)
    (dotfiles_dir / "packages").mkdir(parents=True)
    (dotfiles_dir / "claude-profiles").mkdir(parents=True)
    (dotfiles_dir / "presets" / "homelab.json").write_text(json.dumps({
        "description": "test",
        "package_files": ["apt_common.txt"],
        "backend_overrides": {},
        "claude_settings": "claude_homelab.json",
        "footholds": ["main", "burst"],
    }))
    (dotfiles_dir / "presets" / "work.json").write_text(json.dumps({"package_files": ["apt_common.txt"]}))
    (dotfiles_dir / "packages" / "apt_common.txt").write_text("zsh\ncurl\n")
    (dotfiles_dir / "claude-profiles" / "claude_homelab.json").write_text("{}")

    (dotfiles_dir / "claude" / ".claude").mkdir(parents=True)
    (dotfiles_dir / "claude" / ".claude" / "settings.json").write_text(json.dumps({"model": "base"}))

    monkeypatch.setattr("dotfiles_setup.env._dotfiles_dir", lambda: dotfiles_dir)
    monkeypatch.setattr("dotfiles_setup.env._claude_home", lambda: tmp_path / "claude-home")
    monkeypatch.setattr(state, "state_dir", lambda: tmp_path / "state")
    monkeypatch.setattr(overlay, "find_overlay_root", lambda: None)
    monkeypatch.setattr("dotfiles_setup.update.pull_if_behind", lambda *a, **kw: False)
    monkeypatch.setattr("dotfiles_setup.identity.ensure_git_identity", lambda **kw: tmp_path / "gitconfig.local")
    stub_subprocess(monkeypatch)
    return dotfiles_dir, tmp_path


def _plan_for(tmp_path, prior=None, applied_preset="homelab", overlay_root=None, names=("zsh", "curl"), dry_run=False):
    env = Env(
        state_dir=tmp_path / "state", dotfiles_dir=tmp_path / "dotfiles",
        clock=lambda: datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC),
    )
    preset = Preset("homelab", "test", ("apt_common.txt",), {}, None)
    return _plan(Logger(dry_run=dry_run), env, preset, names, overlay_root, prior)


def _write_optouts(tmp_path, text, name="homelab.txt"):
    package_file = tmp_path / "state" / "packages" / name
    package_file.parent.mkdir(parents=True, exist_ok=True)
    package_file.write_text(text)
    return package_file


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


def test_applied_reports_pin_entries(tmp_path, monkeypatch):
    t = _tooling(tmp_path, monkeypatch, apt=("k9s",))
    applied = applied_after_removals(t, frozenset({"zsh"}), ("github:derailed/k9s",), [])
    assert applied == ("github:derailed/k9s", "zsh")
    assert applied_after_removals(t, frozenset({"zsh"}), ("github:derailed/k9s",), ["github:derailed/k9s"]) == ("zsh",)


def test_plan_without_an_optout_file_wants_everything_and_creates_nothing(isolated_dotfiles):
    _dotfiles_dir, tmp_path = isolated_dotfiles
    assert _plan_for(tmp_path).wanted == frozenset({"zsh", "curl"})
    assert not (tmp_path / "state" / "packages").exists()


def _prior(preset_name, applied, overlay_root=None, optouts_migrated=False):
    return state.MachineState(
        preset_name=preset_name, backend="apt", package_file="x", applied_package_names=applied,
        overlay_root=overlay_root, created_at="t", updated_at="t", optouts_migrated=optouts_migrated,
    )


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


def test_failed_first_run_leaves_the_legacy_file_for_an_identical_retry(isolated_dotfiles, monkeypatch):
    _dotfiles_dir, tmp_path = isolated_dotfiles
    package_file = _write_optouts(tmp_path, "zsh\nslack-desktop\n")
    _save_applied(("curl", "zsh"))
    fail_flow(monkeypatch)
    assert main(["install", "--preset", "homelab"]) == 1
    assert package_file.read_text() == "zsh\nslack-desktop\n"
    retry = _plan_for(tmp_path, state.load_state())
    assert retry.pending == ("slack-desktop",)
    assert retry.wanted == frozenset({"zsh"})


def test_missing_overlay_carries_the_prior_applied_list_forward(isolated_dotfiles, monkeypatch):
    _dotfiles_dir, tmp_path = isolated_dotfiles
    machine(monkeypatch, apt=("extra",))
    saved_root = str(tmp_path / "private")
    state.save_state(_prior("homelab", ("curl", "extra", "zsh"), overlay_root=saved_root), state.state_file())
    assert main(["install", "--preset", "homelab", "--prune"]) == 0
    saved = state.load_state()
    assert saved.applied_package_names == ("curl", "extra", "zsh")
    assert saved.overlay_root == saved_root


def test_migration_optouts_are_not_pending(isolated_dotfiles):
    _dotfiles_dir, tmp_path = isolated_dotfiles
    _write_optouts(tmp_path, "zsh\n")
    assert _plan_for(tmp_path, _prior("homelab", ("curl", "zsh"))).pending == ()


def test_install_marks_the_optouts_migrated(isolated_dotfiles):
    main(["install", "--preset", "homelab"])
    assert state.load_state().optouts_migrated is True


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


def test_overlay_at_a_new_path_is_saved(isolated_dotfiles, monkeypatch):
    _dotfiles_dir, tmp_path = isolated_dotfiles
    moved = tmp_path / "elsewhere"
    moved.mkdir()
    monkeypatch.setattr(overlay, "find_overlay_root", lambda: moved)
    state.save_state(_prior("homelab", ("curl", "zsh"), overlay_root=str(tmp_path / "private")), state.state_file())
    assert main(["install", "--preset", "homelab"]) == 0
    assert state.load_state().overlay_root == str(moved)


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


def test_rule010_successful_install_writes_the_migration_once(isolated_dotfiles):
    _dotfiles_dir, tmp_path = isolated_dotfiles
    package_file = _write_optouts(tmp_path, "zsh\nextra\n")
    assert _plan_for(tmp_path).wanted == frozenset({"zsh"})
    assert package_file.read_text() == "zsh\nextra\n"
    assert main(["install", "--preset", "homelab"]) == 0
    migrated = package_file.read_text()
    assert migrated == f"{optouts.HEADER}\ncurl\n"
    assert main(["install", "--preset", "homelab"]) == 0
    assert package_file.read_text() == migrated
    backups = list((Path.home() / ".local" / "state" / "dotfiles" / "package-backups").glob("*/homelab.txt"))
    assert [b.read_text() for b in backups] == ["zsh\nextra\n"]


def test_state_is_saved_before_the_completion_banner(isolated_dotfiles, monkeypatch):
    saved_at_banner = []
    monkeypatch.setattr(
        "dotfiles_setup.install_flow.print_completion_banner",
        lambda logger: saved_at_banner.append(state.load_state() is not None),
    )
    assert main(["install", "--preset", "homelab"]) == 0
    assert saved_at_banner == [True]


def test_a_failed_migration_write_keeps_the_legacy_file_and_fails_the_run(isolated_dotfiles, monkeypatch, capsys):
    _dotfiles_dir, tmp_path = isolated_dotfiles
    package_file = _write_optouts(tmp_path, "zsh\nextra\n")

    def refuse(path, names, backup):
        raise OSError("disk full")

    monkeypatch.setattr("dotfiles_setup.optouts.write_migration", refuse)
    assert main(["install", "--preset", "homelab"]) == PERSIST_FAILED_EXIT_CODE
    captured = capsys.readouterr()
    out = captured.out + captured.err
    assert f"Could not migrate {package_file}" in out
    assert "stays legacy" in out
    assert package_file.read_text() == "zsh\nextra\n"
    assert state.load_state().optouts_migrated is False
    assert not state.load_state().applied_package_names
    assert _plan_for(tmp_path, state.load_state()).loaded.from_legacy


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


def test_dry_run_install_moves_no_other_presets_file(isolated_dotfiles, capsys):
    _dotfiles_dir, tmp_path = isolated_dotfiles
    other = _write_optouts(tmp_path, "vim\n", name="work.txt")
    assert main(["install", "--preset", "homelab", "--dry-run"]) == 0
    assert other.exists()
    assert not (Path.home() / ".local" / "state" / "dotfiles" / "package-backups").exists()
    assert "Would move" in capsys.readouterr().out


@pytest.mark.parametrize(("applied", "pending"), [(("zsh",), ()), (("curl", "zsh"), ("curl",))])
def test_a_headered_optout_is_pending_only_when_it_was_applied(isolated_dotfiles, applied, pending):
    _dotfiles_dir, tmp_path = isolated_dotfiles
    _write_optouts(tmp_path, f"{optouts.HEADER}\ncurl\n")
    assert _plan_for(tmp_path, _prior("homelab", applied, optouts_migrated=True)).pending == pending


def test_failed_run_leaves_other_presets_files_in_place(isolated_dotfiles, monkeypatch):
    _dotfiles_dir, tmp_path = isolated_dotfiles
    other = _write_optouts(tmp_path, "vim\n", name="work.txt")
    fail_flow(monkeypatch)
    assert main(["install", "--preset", "homelab"]) == 1
    assert other.exists()


def test_successful_run_moves_other_presets_files_to_the_backup(isolated_dotfiles):
    _dotfiles_dir, tmp_path = isolated_dotfiles
    other = _write_optouts(tmp_path, "vim\n", name="work.txt")
    assert main(["install", "--preset", "homelab"]) == 0
    assert not other.exists()
    backups = list((Path.home() / ".local" / "state" / "dotfiles" / "package-backups").glob("*/work.txt"))
    assert [b.read_text() for b in backups] == ["vim\n"]


def _refuse_state_saves(monkeypatch):
    refusing = [True]
    real = state.save_state

    def save(machine_state, path):
        if refusing[0]:
            raise OSError("read-only file system")
        real(machine_state, path)

    monkeypatch.setattr("dotfiles_setup.state.save_state", save)
    return refusing


def _output(capsys):
    captured = capsys.readouterr()
    return captured.out + captured.err


def test_a_failed_state_save_restores_the_legacy_file_and_fails_the_run(isolated_dotfiles, monkeypatch, capsys):
    _dotfiles_dir, tmp_path = isolated_dotfiles
    package_file = _write_optouts(tmp_path, "zsh\nextra\n")
    _save_applied(("curl", "zsh"))
    before = state.load_state()
    _refuse_state_saves(monkeypatch)
    assert main(["install", "--preset", "homelab"]) == PERSIST_FAILED_EXIT_CODE
    out = _output(capsys)
    assert f"Could not save the install state to {state.state_file()}: read-only file system" in out
    assert "retries the migration" in out
    assert "Traceback" not in out
    assert "Machine preset set" not in out
    assert package_file.read_text() == "zsh\nextra\n"
    assert state.load_state() == before


def test_a_retry_after_a_failed_state_save_migrates_identically(isolated_dotfiles, monkeypatch):
    _dotfiles_dir, tmp_path = isolated_dotfiles
    package_file = _write_optouts(tmp_path, "zsh\nextra\n")
    refusing = _refuse_state_saves(monkeypatch)
    assert main(["install", "--preset", "homelab"]) == PERSIST_FAILED_EXIT_CODE
    refusing[0] = False
    assert main(["install", "--preset", "homelab"]) == 0
    assert package_file.read_text() == f"{optouts.HEADER}\ncurl\n"
    assert state.load_state().optouts_migrated is True


def test_a_failed_restore_after_a_failed_state_save_explains_the_headered_file(
    isolated_dotfiles, monkeypatch, capsys,
):
    _dotfiles_dir, tmp_path = isolated_dotfiles
    package_file = _write_optouts(tmp_path, "zsh\nextra\n")
    _refuse_state_saves(monkeypatch)

    def refuse(path, backup):
        raise OSError("permission denied")

    monkeypatch.setattr("dotfiles_setup.optouts.restore_from_backup", refuse)
    assert main(["install", "--preset", "homelab"]) == PERSIST_FAILED_EXIT_CODE
    out = _output(capsys)
    assert f"Could not restore {package_file}: permission denied" in out
    assert "now has a header" in out
    assert "offer to remove" in out
    assert "Traceback" not in out


def test_a_failed_backup_move_reports_and_fails_without_a_traceback(isolated_dotfiles, monkeypatch, capsys):
    _dotfiles_dir, tmp_path = isolated_dotfiles
    other = _write_optouts(tmp_path, "vim\n", name="work.txt")

    def refuse(files, backup):
        raise OSError("no space left on device")

    monkeypatch.setattr("dotfiles_setup.optouts.move_to_backup", refuse)
    assert main(["install", "--preset", "homelab"]) == PERSIST_FAILED_EXIT_CODE
    out = _output(capsys)
    assert f"Could not move {other} to " in out
    assert "package-backups" in out
    assert "no space left on device" in out
    assert "Traceback" not in out
    assert "Machine preset set" not in out
    assert state.load_state().preset_name == "homelab"


def test_a_failed_migration_write_leaves_other_presets_files_in_place(isolated_dotfiles, monkeypatch):
    _dotfiles_dir, tmp_path = isolated_dotfiles
    _write_optouts(tmp_path, "zsh\nextra\n")
    other = _write_optouts(tmp_path, "vim\n", name="work.txt")

    def refuse(path, names, backup):
        raise OSError("disk full")

    monkeypatch.setattr("dotfiles_setup.optouts.write_migration", refuse)
    assert main(["install", "--preset", "homelab"]) == PERSIST_FAILED_EXIT_CODE
    assert other.read_text() == "vim\n"


def test_a_txt_file_that_names_no_preset_is_neither_listed_nor_moved(isolated_dotfiles, capsys):
    _dotfiles_dir, tmp_path = isolated_dotfiles
    _write_optouts(tmp_path, "vim\n", name="work.txt")
    notes = _write_optouts(tmp_path, "keep me\n", name="notes.txt")
    assert main(["install", "--preset", "homelab"]) == 0
    assert notes.read_text() == "keep me\n"
    assert "notes.txt" not in capsys.readouterr().out


def test_without_state_a_legacy_forks_installed_fork_only_name_is_offered(isolated_dotfiles, flow_calls, monkeypatch):
    _dotfiles_dir, tmp_path = isolated_dotfiles
    machine(monkeypatch, apt=("extra",))
    _write_optouts(tmp_path, "zsh\ncurl\nextra\n")
    assert _plan_for(tmp_path).pending == ("extra",)
    assert main(["install", "--preset", "homelab", "--prune"]) == 0
    assert flow_calls[0].removals == ("extra",)


def test_without_state_or_a_legacy_file_nothing_is_pending(isolated_dotfiles):
    _dotfiles_dir, tmp_path = isolated_dotfiles
    assert _plan_for(tmp_path).pending == ()


def test_a_failed_state_save_restores_from_this_runs_backup(isolated_dotfiles, monkeypatch):
    _dotfiles_dir, tmp_path = isolated_dotfiles
    package_file = _write_optouts(tmp_path, "zsh\nextra\n")
    earlier = optouts.backup_dir(Path.home() / ".local" / "state" / "dotfiles", "20260102030405") / "homelab.txt"
    earlier.parent.mkdir(parents=True)
    earlier.write_text("stale\n")
    _refuse_state_saves(monkeypatch)
    env = Env(clock=lambda: datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC))
    assert main(["install", "--preset", "homelab"], env) == PERSIST_FAILED_EXIT_CODE
    assert package_file.read_text() == "zsh\nextra\n"
    assert earlier.read_text() == "stale\n"


def test_optout_for_unlisted_package_warns_only(isolated_dotfiles, capsys):
    _dotfiles_dir, tmp_path = isolated_dotfiles
    _write_optouts(tmp_path, f"{optouts.HEADER}\nghost\n")
    assert _plan_for(tmp_path).wanted == frozenset({"zsh", "curl"})
    assert "ghost" in capsys.readouterr().out


def test_dry_run_does_not_migrate_a_legacy_file(isolated_dotfiles):
    _dotfiles_dir, tmp_path = isolated_dotfiles
    package_file = _write_optouts(tmp_path, "zsh\n")
    main(["install", "--preset", "homelab", "--dry-run"])
    assert package_file.read_text() == "zsh\n"


def test_install_saves_the_wanted_names_as_applied(isolated_dotfiles):
    _dotfiles_dir, tmp_path = isolated_dotfiles
    _write_optouts(tmp_path, f"{optouts.HEADER}\ncurl\n")
    main(["install", "--preset", "homelab"])
    assert state.load_state().applied_package_names == ("zsh",)


def test_install_persists_state(isolated_dotfiles):
    main(["install", "--preset", "homelab"])
    saved = state.load_state()
    assert saved.preset_name == "homelab"
    assert saved.backend == "apt"


def test_install_keeps_the_optout_file_on_rerun(isolated_dotfiles):
    _dotfiles_dir, tmp_path = isolated_dotfiles
    package_file = _write_optouts(tmp_path, f"{optouts.HEADER}\ncurl\n")
    main(["install", "--preset", "homelab"])
    main(["install", "--preset", "homelab"])
    assert package_file.read_text() == f"{optouts.HEADER}\ncurl\n"


def fail_flow(monkeypatch, message="apt-get exploded"):
    result = InstallResult(False, 1, message)
    monkeypatch.setattr("dotfiles_setup.install_flow.run_install", lambda inputs: result)


def test_install_reports_backend_failure(isolated_dotfiles, monkeypatch):
    fail_flow(monkeypatch)
    assert main(["install", "--preset", "homelab"]) == 1


def test_the_claude_settings_exist_before_the_install_steps_run(isolated_dotfiles, tmp_path, monkeypatch):
    seen = {}

    def run_install(inputs):
        seen["settings"] = (tmp_path / "claude-home" / "settings.json").is_file()
        return InstallResult(True, 0, "")

    monkeypatch.setattr("dotfiles_setup.install_flow.run_install", run_install)
    assert main(["install", "--preset", "homelab"]) == 0
    assert seen == {"settings": True}


def test_install_reports_a_failure_with_no_message(isolated_dotfiles, capsys, monkeypatch):
    monkeypatch.setattr("dotfiles_setup.install_flow.run_install", lambda inputs: InstallResult(False, 3, ""))
    assert main(["install", "--preset", "homelab"]) == 3
    assert "exit code 3" in capsys.readouterr().err


def test_dry_run_skips_git_identity(isolated_dotfiles, monkeypatch):
    calls = []
    monkeypatch.setattr(
        "dotfiles_setup.identity.ensure_git_identity",
        lambda **kw: calls.append(kw) or None,
    )
    main(["install", "--preset", "homelab", "--dry-run"])
    assert calls == []


def test_install_merges_the_preset_profile_into_the_generated_settings(isolated_dotfiles):
    dotfiles_dir, tmp_path = isolated_dotfiles
    (dotfiles_dir / "claude-profiles" / "claude_homelab.json").write_text(
        json.dumps({"enabledPlugins": {"sonarqube@official": True}})
    )
    assert main(["install", "--preset", "homelab"]) == 0
    generated = json.loads((tmp_path / "claude-home" / "settings.json").read_text())
    assert generated == {"model": "base", "enabledPlugins": {"sonarqube@official": True}}
    assert not (tmp_path / "state" / "claude-profiles").exists()


def test_dry_run_does_not_create_the_forked_package_file(isolated_dotfiles):
    main(["install", "--preset", "homelab", "--dry-run"])
    assert not (state.package_dir() / "homelab.txt").exists()


def test_dry_run_leaves_an_existing_optout_file_unchanged(isolated_dotfiles):
    package_file = _write_optouts(isolated_dotfiles[1], f"{optouts.HEADER}\nvim\n")
    main(["install", "--preset", "homelab", "--dry-run"])
    assert package_file.read_text() == f"{optouts.HEADER}\nvim\n"


def test_dry_run_hands_the_flow_the_packages_it_would_install(isolated_dotfiles, flow_calls):
    main(["install", "--preset", "homelab", "--dry-run"])
    assert flow_calls[0].packages == frozenset({"zsh", "curl"})


def test_dry_run_skips_state_persistence(isolated_dotfiles):
    main(["install", "--preset", "homelab", "--dry-run"])
    assert state.load_state() is None


def test_install_does_not_persist_state_on_failure(isolated_dotfiles, monkeypatch):
    fail_flow(monkeypatch)
    main(["install", "--preset", "homelab"])
    assert state.load_state() is None


def test_install_forwards_verbosity_to_the_flow(isolated_dotfiles, flow_calls):
    assert main(["install", "--preset", "homelab", "-vv"]) == 0
    assert flow_calls[0].t.logger.verbosity == 2


def test_install_passes_the_overlay_root_to_the_flow(isolated_dotfiles, flow_calls, monkeypatch, tmp_path):
    private_root = tmp_path / "dotfiles-private"
    monkeypatch.setattr(overlay, "find_overlay_root", lambda: private_root)
    assert main(["install", "--preset", "homelab"]) == 0
    assert flow_calls[0].overlay_root == private_root


def test_install_passes_no_overlay_root_when_there_is_none(isolated_dotfiles, flow_calls):
    assert main(["install", "--preset", "homelab"]) == 0
    assert flow_calls[0].overlay_root is None


def test_install_hands_the_flow_the_preset_and_packages(isolated_dotfiles, flow_calls):
    assert main(["install", "--preset", "homelab"]) == 0
    assert flow_calls[0].preset_name == "homelab"
    assert flow_calls[0].packages == frozenset({"zsh", "curl"})


def test_install_raises_helpful_error_for_unknown_preset(isolated_dotfiles, capsys):
    assert main(["install", "--preset", "nonexistent"]) == 1
    assert "nonexistent" in capsys.readouterr().err


def test_install_checks_for_dotfiles_updates_before_the_install_runs(isolated_dotfiles, monkeypatch):
    order = []
    monkeypatch.setattr("dotfiles_setup.update.pull_if_behind", lambda repo, logger: order.append(repo) or False)
    monkeypatch.setattr(
        "dotfiles_setup.install_flow.run_install", lambda inputs: order.append("flow") or InstallResult(True, 0, ""),
    )
    main(["install", "--preset", "homelab"])
    assert order == [isolated_dotfiles[0], "flow"]


def test_install_pulls_private_overlay_after_dotfiles(isolated_dotfiles, monkeypatch, tmp_path):
    private = tmp_path / "private"
    private.mkdir()
    order = []
    monkeypatch.setattr("dotfiles_setup.overlay.find_overlay_root", lambda: private)
    monkeypatch.setattr("dotfiles_setup.update.pull_if_behind", lambda repo, logger: order.append("dotfiles") or False)
    monkeypatch.setattr("dotfiles_setup.update.pull_overlay_if_git", lambda root, logger: order.append(root) or False)
    main(["install", "--preset", "homelab"])
    assert order == ["dotfiles", private]


def test_install_generates_claude_settings_from_base_and_overlay(isolated_dotfiles, monkeypatch, tmp_path):
    private_root = tmp_path / "private"
    (private_root / "claude-settings").mkdir(parents=True)
    (private_root / "claude-settings" / "settings.json").write_text(json.dumps({"extra": True}))
    monkeypatch.setattr(overlay, "find_overlay_root", lambda: private_root)
    assert main(["install", "--preset", "homelab"]) == 0
    generated = json.loads((tmp_path / "claude-home" / "settings.json").read_text())
    assert generated == {"model": "base", "extra": True}


def test_install_backs_up_a_differing_settings_file(isolated_dotfiles, tmp_path):
    claude_home = tmp_path / "claude-home"
    claude_home.mkdir()
    (claude_home / "settings.json").write_text('{"hand": "edited"}')
    assert main(["install", "--preset", "homelab"]) == 0
    (backup,) = claude_home.glob("settings.json.bak-*")
    assert json.loads(backup.read_text()) == {"hand": "edited"}


def test_install_replaces_settings_symlink_without_writing_through(isolated_dotfiles, tmp_path):
    claude_home = tmp_path / "claude-home"
    claude_home.mkdir()
    repo_copy = tmp_path / "repo-settings.json"
    repo_copy.write_text('{"tracked": true}')
    (claude_home / "settings.json").symlink_to(repo_copy)
    assert main(["install", "--preset", "homelab"]) == 0
    assert not (claude_home / "settings.json").is_symlink()
    assert repo_copy.read_text() == '{"tracked": true}'


def test_dry_run_skips_claude_settings_write(isolated_dotfiles, tmp_path):
    assert main(["install", "--preset", "homelab", "--dry-run"]) == 0
    assert not (tmp_path / "claude-home" / "settings.json").exists()


def test_install_keeps_existing_settings_when_staging_fails(isolated_dotfiles, tmp_path, monkeypatch):
    claude_home = tmp_path / "claude-home"
    claude_home.mkdir()
    (claude_home / "settings.json").write_text('{"hand": "edited"}')

    def failing_fdopen(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr("dotfiles_setup.fsutil.os.fdopen", failing_fdopen)
    with pytest.raises(OSError):
        main(["install", "--preset", "homelab"])
    assert (claude_home / "settings.json").read_text() == '{"hand": "edited"}'
    assert not list(claude_home.glob("settings.json.bak-*"))
    assert not list(claude_home.glob("settings.json.*.tmp"))


def test_install_leaves_identical_settings_untouched(isolated_dotfiles, tmp_path):
    assert main(["install", "--preset", "homelab"]) == 0
    settings = tmp_path / "claude-home" / "settings.json"
    os.utime(settings, ns=(0, 0))
    assert main(["install", "--preset", "homelab"]) == 0
    assert settings.stat().st_mtime_ns == 0
    assert not list(settings.parent.glob("settings.json.bak-*"))


def _install_then_edit_settings(tmp_path):
    assert main(["install", "--preset", "homelab"]) == 0
    settings = tmp_path / "claude-home" / "settings.json"
    settings.write_text(json.dumps({**json.loads(settings.read_text()), "hand": "edited"}, indent=2) + "\n")
    return settings


def test_install_records_the_generated_settings_as_the_drift_baseline(isolated_dotfiles, tmp_path):
    assert main(["install", "--preset", "homelab"]) == 0
    baseline = tmp_path / "state" / "settings.last-generated.json"
    assert baseline.read_text() == (tmp_path / "claude-home" / "settings.json").read_text()


def test_install_expands_home_in_the_generated_env_and_its_drift_baseline(
    isolated_dotfiles, monkeypatch, tmp_path,
):
    dotfiles_dir, _ = isolated_dotfiles
    base = {"env": {"PATH": "$HOME/.local/bin:/usr/bin"}, "hooks": {"command": "$HOME/x"}}
    (dotfiles_dir / "claude" / ".claude" / "settings.json").write_text(json.dumps(base))
    monkeypatch.setattr("dotfiles_setup.env._home", lambda: tmp_path / "me")
    assert main(["install", "--preset", "homelab"]) == 0
    generated = (tmp_path / "claude-home" / "settings.json").read_text()
    assert json.loads(generated)["env"]["PATH"] == f"{tmp_path / 'me'}/.local/bin:/usr/bin"
    assert json.loads(generated)["hooks"] == {"command": "$HOME/x"}
    assert (tmp_path / "state" / "settings.last-generated.json").read_text() == generated
    assert main(["install", "--preset", "homelab"]) == 0


def test_rule016_install_stops_when_settings_were_edited_since_the_last_install(
    isolated_dotfiles, plugin_updates, foothold_syncs, tmp_path, capsys,
):
    settings = _install_then_edit_settings(tmp_path)
    edited = settings.read_text()
    assert main(["install", "--preset", "homelab"]) == 3
    assert settings.read_text() == edited
    assert not list(settings.parent.glob("settings.json.bak-*"))
    assert len(plugin_updates) == 1
    assert len(foothold_syncs) == 1
    assert '+  "hand": "edited"' in capsys.readouterr().out


def test_install_accepts_a_base_change_when_settings_were_not_edited(isolated_dotfiles, tmp_path):
    dotfiles_dir, _ = isolated_dotfiles
    assert main(["install", "--preset", "homelab"]) == 0
    (dotfiles_dir / "claude" / ".claude" / "settings.json").write_text(json.dumps({"model": "changed"}))
    assert main(["install", "--preset", "homelab"]) == 0
    settings = tmp_path / "claude-home" / "settings.json"
    assert json.loads(settings.read_text()) == {"model": "changed"}


def test_accept_drift_overwrites_edited_settings_and_keeps_a_backup(isolated_dotfiles, tmp_path):
    settings = _install_then_edit_settings(tmp_path)
    edited = settings.read_text()
    assert main(["install", "--preset", "homelab", "--accept-drift"]) == 0
    (backup,) = settings.parent.glob("settings.json.bak-*")
    assert backup.read_text() == edited
    assert json.loads(settings.read_text()) == {"model": "base"}


def test_rule016_dry_run_reports_settings_drift_and_continues(isolated_dotfiles, tmp_path, capsys):
    settings = _install_then_edit_settings(tmp_path)
    edited = settings.read_text()
    capsys.readouterr()
    assert main(["install", "--preset", "homelab", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "edited since the last install" in out
    assert '+  "hand": "edited"' in out
    assert settings.read_text() == edited


def test_install_updates_claude_plugins_after_a_successful_install(isolated_dotfiles, plugin_updates):
    assert main(["install", "--preset", "homelab"]) == 0
    assert len(plugin_updates) == 1


def test_install_sets_up_the_presets_footholds(isolated_dotfiles, foothold_syncs):
    assert main(["install", "--preset", "homelab"]) == 0
    assert foothold_syncs == [("main", "burst")]


def test_install_of_a_preset_without_footholds_asks_for_none(isolated_dotfiles, foothold_syncs):
    assert main(["install", "--preset", "work"]) == 0
    assert foothold_syncs == [()]


def _add_preset(dotfiles_dir, name):
    (dotfiles_dir / "presets" / f"{name}.json").write_text(json.dumps({
        "description": "test",
        "package_files": ["apt_common.txt"],
        "backend_overrides": {},
        "claude_settings": f"claude_{name}.json",
    }))
    (dotfiles_dir / "claude-profiles" / f"claude_{name}.json").write_text(json.dumps({"enabledPlugins": {}}))


def test_install_syncs_the_new_presets_footholds_when_the_preset_changes(isolated_dotfiles, foothold_syncs):
    dotfiles_dir, _ = isolated_dotfiles
    _add_preset(dotfiles_dir, "personal")
    assert main(["install", "--preset", "homelab"]) == 0
    assert main(["install", "--preset", "personal"]) == 0
    assert foothold_syncs == [("main", "burst"), ()]


def test_install_skips_the_foothold_when_the_install_fails(isolated_dotfiles, foothold_syncs, monkeypatch):
    fail_flow(monkeypatch, "boom")
    main(["install", "--preset", "homelab"])
    assert foothold_syncs == []


def test_install_skips_claude_plugin_update_when_the_install_fails(isolated_dotfiles, plugin_updates, monkeypatch):
    fail_flow(monkeypatch, "boom")
    main(["install", "--preset", "homelab"])
    assert plugin_updates == []


def test_settings_replacement_leaves_a_preexisting_shared_tmp_file_alone(tmp_path):
    target = tmp_path / "settings.json"
    target.write_text("old")
    other_install = tmp_path / "settings.json.tmp"
    other_install.write_text("in flight")
    _replace_settings_target(target, "new", datetime.now(UTC))
    assert target.read_text() == "new"
    assert other_install.read_text() == "in flight"
    assert sorted(p.name for p in tmp_path.glob("settings.json.*.tmp")) == []


def test_install_without_preset_or_saved_state_fails(isolated_dotfiles, capsys):
    assert main(["install"]) == 2
    assert "pass --preset" in capsys.readouterr().err


def test_install_without_preset_fails_before_touching_the_checkout(isolated_dotfiles, monkeypatch):
    calls = []
    monkeypatch.setattr("dotfiles_setup.plan._prepare_checkout", lambda *a: calls.append(a))
    assert main(["install"]) == 2
    assert calls == []


def test_install_without_preset_reuses_the_saved_one(isolated_dotfiles):
    main(["install", "--preset", "homelab"])
    assert main(["install"]) == 0
    assert state.load_state().preset_name == "homelab"


def test_install_preset_overrides_the_saved_one(isolated_dotfiles):
    dotfiles_dir, _tmp = isolated_dotfiles
    (dotfiles_dir / "presets" / "other.json").write_text(json.dumps({
        "description": "test", "package_files": ["apt_common.txt"], "backend_overrides": {},
    }))
    main(["install", "--preset", "homelab"])
    assert main(["install", "--preset", "other"]) == 0
    assert state.load_state().preset_name == "other"


def test_install_without_preset_reports_an_unknown_saved_preset(isolated_dotfiles):
    dotfiles_dir, _tmp = isolated_dotfiles
    main(["install", "--preset", "homelab"])
    (dotfiles_dir / "presets" / "homelab.json").unlink()
    assert main(["install"]) == 1


def test_install_passes_overlay_root_to_git_identity(isolated_dotfiles, monkeypatch, tmp_path):
    """The overlay must be known before ensure_git_identity runs so a private
    overlay's git/gitconfig.local can suppress the interactive prompt."""
    calls = []
    monkeypatch.setattr(
        "dotfiles_setup.identity.ensure_git_identity",
        lambda **kw: calls.append(kw) or tmp_path / "gitconfig.local",
    )
    private_root = tmp_path / "dotfiles-private"
    monkeypatch.setattr(overlay, "find_overlay_root", lambda: private_root)

    assert main(["install", "--preset", "homelab"]) == 0
    assert calls[0]["overlay_root"] == private_root


def test_private_clone_requires_subcommand():
    parser = build_arg_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["private"])


def test_private_clone_requires_repo():
    parser = build_arg_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["private", "clone"])


def test_private_clone_dest_defaults_to_none():
    parser = build_arg_parser()
    args = parser.parse_args(["private", "clone", "--repo", "git@github.com:you/dotfiles-private.git"])
    assert args.dest is None


def test_main_private_clone_clones_to_default_dest(tmp_path, monkeypatch):
    default_root = tmp_path / "dotfiles-private"
    monkeypatch.setattr("dotfiles_setup.overlay.DEFAULT_OVERLAY_ROOT", default_root)
    calls = stub_subprocess(monkeypatch, stdout="")
    assert main(["private", "clone", "--repo", "git@github.com:you/dotfiles-private.git"]) == 0
    assert calls == [["git", "clone", "git@github.com:you/dotfiles-private.git", str(default_root)]]


def test_main_private_clone_honors_dest_override(tmp_path):
    dest = tmp_path / "custom-dest"
    calls = []

    def run(argv, **kwargs):
        calls.append(argv)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    argv = ["private", "clone", "--repo", "git@example.com/x.git", "--dest", str(dest)]
    assert main(argv, Env(run=run)) == 0
    assert calls[0][-1] == str(dest)


def _save_preset(tmp_path, preset_name):
    state.save_state(state.MachineState(
        preset_name=preset_name, backend="apt", package_file="x", applied_package_names=(),
        overlay_root=None, created_at="t", updated_at="t",
    ), state.state_file(tmp_path))


def test_foothold_requires_subcommand():
    parser = build_arg_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["foothold"])


def test_main_foothold_restart_restarts_the_installed_footholds(tmp_path, monkeypatch):
    _save_preset(tmp_path, "homelab")
    restarted = []
    monkeypatch.setattr("dotfiles_setup.foothold.restart_footholds", lambda logger, run: restarted.append(run) or True)
    assert main(["foothold", "restart"], Env(state_dir=tmp_path)) == 0
    assert len(restarted) == 1


def test_main_foothold_restart_fails_when_the_restart_fails(tmp_path, monkeypatch):
    _save_preset(tmp_path, "homelab")
    monkeypatch.setattr("dotfiles_setup.foothold.restart_footholds", lambda logger, run: False)
    assert main(["foothold", "restart"], Env(state_dir=tmp_path)) == 1


def test_main_foothold_restart_without_a_saved_preset_exits_2(tmp_path):
    assert main(["foothold", "restart"], Env(state_dir=tmp_path)) == 2


def test_install_uses_injected_clock_and_paths(isolated_dotfiles, tmp_path):
    dotfiles_dir, _ = isolated_dotfiles
    clock_value = datetime(2030, 1, 2, 3, 4, 5, tzinfo=UTC)
    env = Env(
        clock=lambda: clock_value, claude_home=tmp_path / "injected-claude",
        state_dir=tmp_path / "injected-state", dotfiles_dir=dotfiles_dir,
    )
    assert main(["install", "--preset", "homelab"], env) == 0
    saved = state.load_state(tmp_path / "injected-state" / "state.json")
    assert saved.created_at == clock_value.isoformat()
    assert (tmp_path / "injected-claude" / "settings.json").is_file()
    assert not (tmp_path / "injected-state" / "packages").exists()


def test_install_builds_backend_through_injected_factory(isolated_dotfiles):
    dotfiles_dir, _ = isolated_dotfiles
    seen = []

    def factory(directory, overrides):
        seen.append((directory, overrides))
        return AptBackend(dotfiles_dir=directory, backend_overrides=overrides)

    assert main(["install", "--preset", "homelab"], Env(dotfiles_dir=dotfiles_dir, backend_factory=factory)) == 0
    assert seen == [(dotfiles_dir, {})]


def test_env_now_iso_uses_clock():
    env = Env(clock=lambda: datetime(2030, 1, 2, tzinfo=UTC))
    assert env.now_iso() == "2030-01-02T00:00:00+00:00"


def test_each_subcommand_parser_is_built_by_its_own_function():
    parser = build_arg_parser()
    assert parser.parse_args(["install", "-vv", "--force"]).verbosity == 2
    assert parser.parse_args(["private", "clone", "--repo", "x"]).private_command == "clone"


def test_main_private_clone_dry_run_does_not_clone(tmp_path, monkeypatch, capsys):
    def unexpected_run(argv, **kwargs):
        raise AssertionError("git clone should not run in dry-run mode")

    monkeypatch.setattr("dotfiles_setup.tooling.subprocess.run", unexpected_run)

    dest = tmp_path / "dotfiles-private"
    assert main(["private", "clone", "--repo", "git@example.com/x.git", "--dest", str(dest), "--dry-run"]) == 0
    assert "DRY-RUN" in capsys.readouterr().out
    assert not dest.exists()


def test_main_private_clone_returns_nonzero_on_git_failure(tmp_path, monkeypatch, capsys):
    stub_subprocess(monkeypatch, returncode=128, stdout="", stderr="fatal: repository not found")
    dest = tmp_path / "dotfiles-private"
    assert main(["private", "clone", "--repo", "git@example.com/x.git", "--dest", str(dest)]) == 128
    assert "not found" in capsys.readouterr().err


def test_install_force_flag_reaches_the_flow(isolated_dotfiles, flow_calls):
    assert main(["install", "--preset", "homelab", "--force"]) == 0
    assert flow_calls[0].force is True


def test_force_is_off_by_default(isolated_dotfiles, flow_calls):
    assert main(["install", "--preset", "homelab"]) == 0
    assert flow_calls[0].force is False


def test_a_failed_step_offers_a_rollback(isolated_dotfiles, monkeypatch):
    offered = []
    failed = InstallResult(False, 1, "Step 'x' failed.", rollback_pending=True)
    monkeypatch.setattr("dotfiles_setup.install_flow.run_install", lambda inputs: failed)
    monkeypatch.setattr("dotfiles_setup.rollback.offer_rollback", lambda ctx, interactive: offered.append(ctx))
    assert main(["install", "--preset", "homelab"]) == 1
    assert len(offered) == 1


def test_a_failure_with_nothing_to_roll_back_offers_nothing(isolated_dotfiles, monkeypatch):
    monkeypatch.setattr("dotfiles_setup.install_flow.run_install", lambda inputs: InstallResult(False, 1, "no"))
    monkeypatch.setattr(
        "dotfiles_setup.rollback.offer_rollback", lambda ctx, interactive: pytest.fail("no rollback expected"),
    )
    assert main(["install", "--preset", "homelab"]) == 1


def test_dry_run_install_writes_nothing_to_disk(isolated_dotfiles):
    _, tmp_path = isolated_dotfiles
    assert main(["install", "--preset", "homelab", "--dry-run"]) == 0
    assert not list((tmp_path / "claude-home").rglob("*"))
    assert not (tmp_path / "state" / "state.json").exists()
    assert not (tmp_path / "state" / "claude-profiles").exists()


def test_switching_presets_retires_the_old_optout_file_and_regenerates_state(isolated_dotfiles, foothold_syncs):
    dotfiles_dir, tmp_path = isolated_dotfiles
    _add_preset(dotfiles_dir, "personal")
    old = _write_optouts(tmp_path, f"{optouts.HEADER}\ncurl\n")
    assert main(["install", "--preset", "homelab"]) == 0
    assert main(["install", "--preset", "personal"]) == 0
    assert not old.exists()
    assert state.load_state().preset_name == "personal"
    assert foothold_syncs[-1] == ()


def _ask(answer):
    asked = []
    return asked, lambda prompt: asked.append(prompt) or answer


@pytest.mark.parametrize("answer", ["y", "yes", "Y", "YES"])
def test_rule007_confirm_yes_applies(answer, capsys):
    asked, ask = _ask(answer)
    assert confirm_removals(Logger(dry_run=False), ("htop",), prune=False, interactive=True, ask=ask)
    assert asked == ["Remove these packages? [y/N] "]
    assert "htop" in capsys.readouterr().out


@pytest.mark.parametrize("answer", ["", "n", "no", "maybe"])
def test_rule007_confirm_other_answers_decline(answer, capsys):
    _, ask = _ask(answer)
    assert not confirm_removals(Logger(dry_run=False), ("htop",), prune=False, interactive=True, ask=ask)
    assert "Removals declined; they will be offered again next run." in capsys.readouterr().out


def test_rule007_confirm_non_interactive_declines_without_prune(capsys):
    asked, ask = _ask("y")
    assert not confirm_removals(Logger(dry_run=False), ("htop",), prune=False, interactive=False, ask=ask)
    assert asked == []
    assert "pass --prune to apply" in capsys.readouterr().out


def test_confirm_prune_applies_without_asking():
    asked, ask = _ask("n")
    assert confirm_removals(Logger(dry_run=False), ("htop",), prune=True, interactive=False, ask=ask)
    assert asked == []


def test_confirm_with_nothing_pending_is_silent(capsys):
    asked, ask = _ask("y")
    assert not confirm_removals(Logger(dry_run=False), (), prune=True, interactive=True, ask=ask)
    assert asked == []
    assert capsys.readouterr().out == ""


def test_confirm_lists_manual_entries_separately(capsys):
    confirm_removals(Logger(dry_run=False), ("htop", "flatpak:org.x.App", "sdkman"), prune=True, interactive=False)
    out = capsys.readouterr().out
    assert "htop" in out
    assert "flatpak:org.x.App" in out
    assert "dropped, remove manually" in out
    assert "sdkman" in out


def _raise(error):
    def ask(prompt):
        raise error

    return ask


def test_rule007_confirm_treats_end_of_input_as_declined(capsys):
    assert not confirm_removals(Logger(dry_run=False), ("htop",), prune=False, interactive=True, ask=_raise(EOFError))
    assert "Removals declined; they will be offered again next run." in capsys.readouterr().out


def test_confirm_lets_an_interrupt_propagate():
    logger = Logger(dry_run=False)
    ask = _raise(KeyboardInterrupt)
    with pytest.raises(KeyboardInterrupt):
        confirm_removals(logger, ("htop",), prune=False, interactive=True, ask=ask)


def test_an_interrupt_at_the_prompt_exits_130_before_any_step(isolated_dotfiles, flow_calls, monkeypatch):
    class InterruptedTty(io.StringIO):
        def isatty(self):
            return True

        def readline(self, *args):
            raise KeyboardInterrupt

    machine(monkeypatch, apt=("htop",))
    _save_applied(("curl", "htop", "zsh"))
    monkeypatch.setattr("sys.stdin", InterruptedTty(""))
    assert main(["install", "--preset", "homelab"]) == 130
    assert flow_calls == []
    assert state.load_state().applied_package_names == ("curl", "htop", "zsh")


def test_an_interrupt_at_the_prompt_leaves_the_claude_settings_unwritten(isolated_dotfiles, monkeypatch):
    _dotfiles_dir, tmp_path = isolated_dotfiles

    class InterruptedTty(io.StringIO):
        def isatty(self):
            return True

        def readline(self, *args):
            raise KeyboardInterrupt

    machine(monkeypatch, apt=("htop",))
    _save_applied(("curl", "htop", "zsh"))
    monkeypatch.setattr("sys.stdin", InterruptedTty(""))
    assert main(["install", "--preset", "homelab"]) == 130
    assert not (tmp_path / "claude-home" / "settings.json").exists()
    assert not settings_drift.baseline_path(tmp_path / "state").exists()


def test_confirm_with_only_manual_entries_lists_them_without_asking(capsys):
    asked, ask = _ask("y")
    assert not confirm_removals(Logger(dry_run=False), ("sdkman",), prune=False, interactive=True, ask=ask)
    assert asked == []
    assert "remove manually: sdkman" in capsys.readouterr().out


def test_prune_flag_parses():
    assert build_arg_parser().parse_args(["install", "--prune"]).prune is True
    assert build_arg_parser().parse_args(["install"]).prune is False


def machine(monkeypatch, apt=(), flatpaks=()):
    def run(argv, **kwargs):
        if argv[0] == "dpkg-query":
            out = "".join(f"ii  {name} 1.0\n" for name in apt)
        else:
            out = ""
        code = 0 if argv[:3] != ["flatpak", "info", "--user"] or argv[3] in flatpaks else 1
        return SimpleNamespace(returncode=code, stdout=out, stderr="")

    monkeypatch.setattr("dotfiles_setup.tooling.subprocess.run", run)


def _save_applied(applied):
    state.save_state(_prior("homelab", applied), state.state_file())


def _tooling(tmp_path, monkeypatch, apt=(), flatpaks=()):
    machine(monkeypatch, apt, flatpaks)
    return Tooling(Logger(dry_run=False), tmp_path)


def test_applied_keeps_installed_pending_names_that_were_not_removed(tmp_path, monkeypatch):
    t = _tooling(tmp_path, monkeypatch, apt=("htop",))
    applied = applied_after_removals(t, frozenset({"zsh"}), ("htop",), [])
    assert applied == ("htop", "zsh")


def test_rule009_applied_drops_removed_names(tmp_path, monkeypatch):
    t = _tooling(tmp_path, monkeypatch, apt=("htop", "vim"))
    applied = applied_after_removals(t, frozenset({"zsh"}), ("htop", "vim"), ["htop"])
    assert applied == ("vim", "zsh")


def test_applied_drops_pending_names_that_are_not_installed(tmp_path, monkeypatch):
    t = _tooling(tmp_path, monkeypatch)
    assert applied_after_removals(t, frozenset({"zsh"}), ("htop",), []) == ("zsh",)


def test_applied_drops_manual_entries(tmp_path, monkeypatch):
    t = _tooling(tmp_path, monkeypatch)
    assert applied_after_removals(t, frozenset({"zsh"}), ("sdkman",), []) == ("zsh",)


def test_applied_keeps_flatpaks_with_their_prefix(tmp_path, monkeypatch):
    t = _tooling(tmp_path, monkeypatch, flatpaks=("org.x.App", "org.y.App"))
    applied = applied_after_removals(
        t, frozenset({"zsh"}), ("flatpak:org.x.App", "flatpak:org.y.App"), ["flatpak:org.y.App"],
    )
    assert applied == ("flatpak:org.x.App", "zsh")


def test_prune_applies_non_interactively(isolated_dotfiles, flow_calls, monkeypatch):
    machine(monkeypatch, apt=("htop",))
    _save_applied(("curl", "htop", "zsh"))
    assert main(["install", "--preset", "homelab", "--prune"]) == 0
    assert flow_calls[0].removals == ("htop",)


def test_rule009_declined_removals_stay_in_applied_state(isolated_dotfiles, flow_calls, monkeypatch):
    machine(monkeypatch, apt=("htop",))
    _save_applied(("curl", "htop", "zsh"))
    assert main(["install", "--preset", "homelab"]) == 0
    assert flow_calls[0].removals == ()
    assert state.load_state().applied_package_names == ("curl", "htop", "zsh")


def test_rule009_completed_removals_leave_applied_state(isolated_dotfiles, monkeypatch):
    machine(monkeypatch, apt=("htop",))
    _save_applied(("curl", "htop", "zsh"))

    def run_install(inputs):
        inputs.removed.extend(inputs.removals)
        return InstallResult(True, 0, "")

    monkeypatch.setattr("dotfiles_setup.install_flow.run_install", run_install)
    assert main(["install", "--preset", "homelab", "--prune"]) == 0
    assert state.load_state().applied_package_names == ("curl", "zsh")


def test_interactive_yes_approves_removals(isolated_dotfiles, flow_calls, monkeypatch):
    class Tty(io.StringIO):
        def isatty(self):
            return True

    machine(monkeypatch, apt=("htop",))
    _save_applied(("curl", "htop", "zsh"))
    monkeypatch.setattr("sys.stdin", Tty("y\n"))
    assert main(["install", "--preset", "homelab"]) == 0
    assert flow_calls[0].removals == ("htop",)


def test_migration_offers_installed_fork_only_packages(isolated_dotfiles, flow_calls, monkeypatch):
    _dotfiles_dir, tmp_path = isolated_dotfiles
    machine(monkeypatch, apt=("curl", "slack-desktop", "zsh"))
    _write_optouts(tmp_path, "zsh\ncurl\nslack-desktop\nnever-installed\n")
    _save_applied(("curl", "zsh"))
    assert main(["install", "--preset", "homelab", "--prune"]) == 0
    assert flow_calls[0].removals == ("slack-desktop",)


def test_migration_messages_show_at_default_verbosity(isolated_dotfiles, capsys):
    _dotfiles_dir, tmp_path = isolated_dotfiles
    _write_optouts(tmp_path, "zsh\nextra\n")
    _write_optouts(tmp_path, "vim\n", name="work.txt")
    _plan_for(tmp_path)
    out = capsys.readouterr().out
    assert "Will migrate" in out
    assert "work.txt" in out
    assert "only in the old file: extra" in out


def test_prompt_lists_only_installed_removals(isolated_dotfiles, flow_calls, monkeypatch, capsys):
    machine(monkeypatch, apt=("htop",))
    _save_applied(("curl", "htop", "vim", "zsh"))
    assert main(["install", "--preset", "homelab", "--prune"]) == 0
    assert flow_calls[0].removals == ("htop",)
    assert "vim" not in capsys.readouterr().out


def test_no_prompt_when_no_removal_is_installed(isolated_dotfiles, flow_calls, monkeypatch, capsys):
    class Tty(io.StringIO):
        def isatty(self):
            return True

    machine(monkeypatch)
    _save_applied(("curl", "sdkman", "vim", "zsh"))
    monkeypatch.setattr("sys.stdin", Tty("y\n"))
    monkeypatch.setattr("builtins.input", lambda prompt="": pytest.fail("no prompt expected"))
    assert main(["install", "--preset", "homelab"]) == 0
    assert flow_calls[0].removals == ()
    out = capsys.readouterr().out
    assert "vim" not in out
    assert out.count("remove manually") == 1


def test_rule007_dry_run_lists_removals_and_does_not_prompt(isolated_dotfiles, flow_calls, monkeypatch, capsys):
    machine(monkeypatch, apt=("htop",))
    _save_applied(("curl", "htop", "zsh"))
    monkeypatch.setattr("builtins.input", lambda prompt="": pytest.fail("no prompt expected"))
    assert main(["install", "--preset", "homelab", "--dry-run", "--prune"]) == 0
    assert flow_calls[0].removals == ()
    assert "htop" in capsys.readouterr().out

