from pathlib import Path

from dotfiles_setup.optouts import (
    HEADER,
    backup_dir,
    is_legacy,
    migrate,
    read_optouts,
    retire_other_presets,
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


def test_migrate_converts_fork_to_optouts(tmp_path: Path):
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


def test_retire_other_presets_moves_not_deletes(tmp_path: Path):
    (tmp_path / "work.txt").write_text("a\n")
    (tmp_path / "home.txt").write_text("b\n")
    backups = tmp_path / "bak"
    moved = retire_other_presets(tmp_path, "work", backups, dry_run=False)
    assert moved == ("home.txt",)
    assert (tmp_path / "work.txt").exists()
    assert not (tmp_path / "home.txt").exists()
    assert (backups / "home.txt").read_text() == "b\n"


def test_retire_dry_run_moves_nothing(tmp_path: Path):
    (tmp_path / "home.txt").write_text("b\n")
    moved = retire_other_presets(tmp_path, "work", tmp_path / "bak", dry_run=True)
    assert moved == ("home.txt",)
    assert (tmp_path / "home.txt").exists()


def test_backup_dir_layout(tmp_path: Path):
    assert backup_dir(tmp_path, "t1") == tmp_path / "package-backups" / "t1"
