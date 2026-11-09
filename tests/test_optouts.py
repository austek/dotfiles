from pathlib import Path

import pytest
from dotfiles_setup.optouts import (
    HEADER,
    backup_dir,
    is_legacy,
    migrate,
    move_to_backup,
    other_preset_files,
    read_optouts,
    restore_from_backup,
    write_migration,
)

LEGACY = "bat\njq\ngit\n# --- added by reconcile ---\nextra\n"


def test_read_optouts_ignores_comments_and_blanks(tmp_path: Path):
    f = tmp_path / "work.txt"
    f.write_text(f"{HEADER}\n\n# note\nbat\n jq \n")
    assert read_optouts(f) == frozenset({"bat", "jq"})


def test_read_optouts_missing_is_empty(tmp_path: Path):
    assert read_optouts(tmp_path / "none.txt") == frozenset()


def test_is_legacy_true_without_header(tmp_path: Path):
    f = tmp_path / "work.txt"
    f.write_text(LEGACY)
    assert is_legacy(f)


def test_is_legacy_false_with_header_or_missing(tmp_path: Path):
    f = tmp_path / "work.txt"
    f.write_text(f"\n{HEADER}\nbat\n")
    assert not is_legacy(f)
    assert not is_legacy(tmp_path / "none.txt")


def test_is_legacy_false_with_a_comment_above_the_header(tmp_path: Path):
    f = tmp_path / "work.txt"
    f.write_text(f"# my opt-outs\n{HEADER}\nbat\n")
    assert not is_legacy(f)


def test_rule010_migrate_converts_fork_to_optouts(tmp_path: Path):
    f = tmp_path / "work.txt"
    f.write_text(LEGACY)
    backups = tmp_path / "bak"
    result = migrate(f, ["bat", "jq", "git", "curl", "zsh"], backups, dry_run=False)
    assert result.optouts == frozenset({"curl", "zsh"})
    assert result.fork_only == ("extra",)
    assert (backups / "work.txt").read_text() == LEGACY
    assert f.read_text() == f"{HEADER}\ncurl\nzsh\n"


def test_migrate_dry_run_writes_nothing(tmp_path: Path):
    f = tmp_path / "work.txt"
    f.write_text(LEGACY)
    backups = tmp_path / "bak"
    result = migrate(f, ["bat", "curl"], backups, dry_run=True)
    assert result.optouts == frozenset({"curl"})
    assert f.read_text() == LEGACY
    assert not backups.exists()


def test_other_preset_files_lists_without_moving(tmp_path: Path):
    (tmp_path / "work.txt").write_text("a\n")
    (tmp_path / "home.txt").write_text("b\n")
    assert other_preset_files(tmp_path, "work", {"work", "home"}) == (tmp_path / "home.txt",)
    assert (tmp_path / "home.txt").exists()


def test_other_preset_files_skips_a_txt_that_names_no_preset(tmp_path: Path):
    (tmp_path / "homelab.txt").write_text("a\n")
    (tmp_path / "work.txt").write_text("b\n")
    (tmp_path / "notes.txt").write_text("c\n")
    assert other_preset_files(tmp_path, "homelab", {"homelab", "work", "personal"}) == (tmp_path / "work.txt",)


def test_migrations_with_the_same_backup_dir_keep_both_backups(tmp_path: Path):
    fork = tmp_path / "work.txt"
    backups = tmp_path / "bak"
    fork.write_text("first\n")
    first = write_migration(fork, frozenset({"vim"}), backups)
    fork.write_text("second\n")
    second = write_migration(fork, frozenset({"vim"}), backups)
    assert first != second
    assert (first.read_text(), second.read_text()) == ("first\n", "second\n")
    restore_from_backup(fork, second)
    assert fork.read_text() == "second\n"


def test_move_to_backup_moves_not_deletes(tmp_path: Path):
    (tmp_path / "home.txt").write_text("b\n")
    backups = tmp_path / "bak"
    move_to_backup((tmp_path / "home.txt",), backups)
    assert not (tmp_path / "home.txt").exists()
    assert (backups / "home.txt").read_text() == "b\n"


def test_a_failed_migration_write_leaves_the_legacy_file_whole(tmp_path: Path, monkeypatch):
    fork = tmp_path / "work.txt"
    fork.write_text(LEGACY)

    def refuse(self, target):
        raise OSError("disk full")

    monkeypatch.setattr(Path, "replace", refuse)
    backups = tmp_path / "bak"
    kept = frozenset({"vim"})
    with pytest.raises(OSError):
        write_migration(fork, kept, backups)
    assert fork.read_text() == LEGACY
    assert sorted(p.name for p in tmp_path.iterdir()) == ["bak", "work.txt"]


def test_restore_from_backup_puts_the_legacy_file_back(tmp_path: Path):
    fork = tmp_path / "work.txt"
    fork.write_text(LEGACY)
    backups = tmp_path / "bak"
    saved = write_migration(fork, frozenset({"vim"}), backups)
    restore_from_backup(fork, saved)
    assert fork.read_text() == LEGACY
    assert is_legacy(fork)


def test_backup_dir_layout(tmp_path: Path):
    assert backup_dir(tmp_path, "t1") == tmp_path / "package-backups" / "t1"
