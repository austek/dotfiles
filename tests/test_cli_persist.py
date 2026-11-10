from datetime import UTC, datetime
from pathlib import Path

from cli_support import (
    _add_preset,
    _plan_for,
    _prior,
    _save_applied,
    _write_optouts,
    fail_flow,
    machine,
)
from dotfiles_setup import optouts, overlay, state
from dotfiles_setup.cli import Env, main
from dotfiles_setup.install_cmd import PERSIST_FAILED_EXIT_CODE


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


def test_install_marks_the_optouts_migrated(isolated_dotfiles):
    main(["install", "--preset", "homelab"])
    assert state.load_state().optouts_migrated is True


def test_overlay_at_a_new_path_is_saved(isolated_dotfiles, monkeypatch):
    _dotfiles_dir, tmp_path = isolated_dotfiles
    moved = tmp_path / "elsewhere"
    moved.mkdir()
    monkeypatch.setattr(overlay, "find_overlay_root", lambda: moved)
    state.save_state(_prior("homelab", ("curl", "zsh"), overlay_root=str(tmp_path / "private")), state.state_file())
    assert main(["install", "--preset", "homelab"]) == 0
    assert state.load_state().overlay_root == str(moved)


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


def test_dry_run_install_moves_no_other_presets_file(isolated_dotfiles, capsys):
    _dotfiles_dir, tmp_path = isolated_dotfiles
    other = _write_optouts(tmp_path, "vim\n", name="work.txt")
    assert main(["install", "--preset", "homelab", "--dry-run"]) == 0
    assert other.exists()
    assert not (Path.home() / ".local" / "state" / "dotfiles" / "package-backups").exists()
    assert "Would move" in capsys.readouterr().out


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


def test_dry_run_does_not_create_the_forked_package_file(isolated_dotfiles):
    main(["install", "--preset", "homelab", "--dry-run"])
    assert not (state.package_dir() / "homelab.txt").exists()


def test_dry_run_leaves_an_existing_optout_file_unchanged(isolated_dotfiles):
    package_file = _write_optouts(isolated_dotfiles[1], f"{optouts.HEADER}\nvim\n")
    main(["install", "--preset", "homelab", "--dry-run"])
    assert package_file.read_text() == f"{optouts.HEADER}\nvim\n"


def test_dry_run_skips_state_persistence(isolated_dotfiles):
    main(["install", "--preset", "homelab", "--dry-run"])
    assert state.load_state() is None


def test_install_does_not_persist_state_on_failure(isolated_dotfiles, monkeypatch):
    fail_flow(monkeypatch)
    main(["install", "--preset", "homelab"])
    assert state.load_state() is None


def test_switching_presets_retires_the_old_optout_file_and_regenerates_state(isolated_dotfiles, foothold_syncs):
    dotfiles_dir, tmp_path = isolated_dotfiles
    _add_preset(dotfiles_dir, "personal")
    old = _write_optouts(tmp_path, f"{optouts.HEADER}\ncurl\n")
    assert main(["install", "--preset", "homelab"]) == 0
    assert main(["install", "--preset", "personal"]) == 0
    assert not old.exists()
    assert state.load_state().preset_name == "personal"
    assert foothold_syncs[-1] == ()
