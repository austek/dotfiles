from pathlib import Path

from dotfiles_setup import tools, zsh_cache
from dotfiles_setup.log import Logger

COMPLETIONS = ".config/zsh/completions"
OMZ_COMPLETIONS = ".oh-my-zsh/custom/completions"
FUNCTIONS = ".config/zsh/functions"
STORE = ".local/state/dotfiles/zsh-completions.sha256"


def setup(tmp_path, dry_run=False):
    home = tmp_path / "home"
    for directory in (COMPLETIONS, OMZ_COMPLETIONS, FUNCTIONS):
        (home / directory).mkdir(parents=True, exist_ok=True)
    return tools.Tooling(Logger(dry_run=dry_run, verbosity=1), home), home


def completer(home: Path, name: str, header: str = "#compdef x", body: str = "body", where: str = COMPLETIONS) -> Path:
    path = home / where / name
    path.write_text(f"{header}\n{body}\n")
    return path


def dump(home: Path, name: str = ".zcompdump-host-5.9") -> Path:
    path = home / name
    path.write_text("dump")
    return path


def stored(home: Path) -> str:
    return (home / STORE).read_text().strip()


def test_the_first_run_drops_an_existing_dump_and_remembers_the_completions(tmp_path):
    t, home = setup(tmp_path)
    completer(home, "_dfctl")
    cache = dump(home)
    assert zsh_cache.refresh_zsh_completion_cache(t)
    assert not cache.exists()
    assert stored(home) == zsh_cache.fingerprint(home)


def test_unchanged_completions_leave_the_dump_alone(tmp_path):
    t, home = setup(tmp_path)
    completer(home, "_dfctl")
    zsh_cache.refresh_zsh_completion_cache(t)
    cache = dump(home)
    assert zsh_cache.refresh_zsh_completion_cache(t)
    assert cache.read_text() == "dump"


def test_a_rename_that_keeps_the_file_count_drops_the_dump(tmp_path):
    t, home = setup(tmp_path)
    old = completer(home, "_dotfiles-setup", "#compdef dotfiles-setup")
    zsh_cache.refresh_zsh_completion_cache(t)
    old.unlink()
    completer(home, "_dfctl", "#compdef dfctl")
    cache = dump(home)
    zsh_cache.refresh_zsh_completion_cache(t)
    assert not cache.exists()


def test_a_rename_that_keeps_the_header_drops_the_dump(tmp_path):
    t, home = setup(tmp_path)
    old = completer(home, "_one", "#compdef same")
    zsh_cache.refresh_zsh_completion_cache(t)
    old.unlink()
    completer(home, "_two", "#compdef same")
    cache = dump(home)
    zsh_cache.refresh_zsh_completion_cache(t)
    assert not cache.exists()


def test_a_new_oh_my_zsh_completion_drops_the_dump(tmp_path):
    t, home = setup(tmp_path)
    zsh_cache.refresh_zsh_completion_cache(t)
    cache = dump(home)
    completer(home, "_claude", where=OMZ_COMPLETIONS)
    zsh_cache.refresh_zsh_completion_cache(t)
    assert not cache.exists()


def test_a_changed_compdef_header_drops_the_dump(tmp_path):
    t, home = setup(tmp_path)
    completer(home, "_tool", "#compdef one")
    zsh_cache.refresh_zsh_completion_cache(t)
    completer(home, "_tool", "#compdef two")
    cache = dump(home)
    zsh_cache.refresh_zsh_completion_cache(t)
    assert not cache.exists()


def test_a_change_below_the_header_does_not_drop_the_dump(tmp_path):
    t, home = setup(tmp_path)
    completer(home, "_tool", body="first")
    zsh_cache.refresh_zsh_completion_cache(t)
    completer(home, "_tool", body="second")
    cache = dump(home)
    zsh_cache.refresh_zsh_completion_cache(t)
    assert cache.exists()


def test_files_that_are_not_completers_do_not_change_the_fingerprint(tmp_path):
    t, home = setup(tmp_path)
    completer(home, "_dfctl")
    zsh_cache.refresh_zsh_completion_cache(t)
    (home / OMZ_COMPLETIONS / "README").write_text("not a completer\n")
    cache = dump(home)
    zsh_cache.refresh_zsh_completion_cache(t)
    assert cache.exists()


def test_helper_functions_loaded_after_compinit_do_not_change_the_fingerprint(tmp_path):
    t, home = setup(tmp_path)
    completer(home, "_dfctl")
    zsh_cache.refresh_zsh_completion_cache(t)
    (home / FUNCTIONS / "_claude_account_ls").write_text("# helper\n")
    cache = dump(home)
    zsh_cache.refresh_zsh_completion_cache(t)
    assert cache.exists()


def test_every_dump_variant_is_removed_and_other_files_are_kept(tmp_path):
    t, home = setup(tmp_path)
    plain, host, compiled = dump(home, ".zcompdump"), dump(home, ".zcompdump-h-5.9"), dump(home, ".zcompdump-h-5.9.zwc")
    keep = home / ".zshrc"
    keep.write_text("rc")
    zsh_cache.refresh_zsh_completion_cache(t)
    assert [p.exists() for p in (plain, host, compiled)] == [False, False, False]
    assert keep.read_text() == "rc"


def test_a_directory_matching_the_dump_pattern_is_skipped_and_later_dumps_still_go(tmp_path, capsys):
    t, home = setup(tmp_path)
    folder = home / ".zcompdump-cache"
    folder.mkdir()
    (folder / "inner").write_text("keep")
    later = dump(home, ".zcompdump-host-5.9")
    zsh_cache.refresh_zsh_completion_cache(t)
    assert (folder / "inner").read_text() == "keep"
    assert not later.exists()
    assert "WARNING" not in capsys.readouterr().out


def test_a_symlinked_dump_is_unlinked_without_touching_its_target(tmp_path):
    t, home = setup(tmp_path)
    target = tmp_path / "elsewhere"
    target.write_text("keep")
    (home / ".zcompdump").symlink_to(target)
    zsh_cache.refresh_zsh_completion_cache(t)
    assert not (home / ".zcompdump").is_symlink()
    assert target.read_text() == "keep"


def test_a_dangling_completion_link_does_not_break_the_fingerprint(tmp_path):
    t, home = setup(tmp_path)
    (home / COMPLETIONS / "_gone").symlink_to(home / "missing")
    assert zsh_cache.refresh_zsh_completion_cache(t)
    assert len(zsh_cache.fingerprint(home)) == 64


def test_missing_completion_directories_are_fine(tmp_path):
    home = tmp_path / "bare"
    home.mkdir()
    t = tools.Tooling(Logger(dry_run=False, verbosity=1), home)
    assert zsh_cache.refresh_zsh_completion_cache(t)
    assert stored(home) == zsh_cache.fingerprint(home)


def test_a_dry_run_changes_nothing(tmp_path):
    t, home = setup(tmp_path, dry_run=True)
    completer(home, "_dfctl")
    cache = dump(home)
    assert zsh_cache.refresh_zsh_completion_cache(t)
    assert cache.exists()
    assert not (home / STORE).exists()


def test_a_dry_run_is_silent_when_nothing_changed(tmp_path, capsys):
    real, home = setup(tmp_path)
    completer(home, "_dfctl")
    zsh_cache.refresh_zsh_completion_cache(real)
    capsys.readouterr()
    zsh_cache.refresh_zsh_completion_cache(tools.Tooling(Logger(dry_run=True, verbosity=1), home))
    assert "Would remove" not in capsys.readouterr().out


def test_a_dump_that_cannot_be_removed_warns_and_is_retried_next_run(tmp_path, monkeypatch, capsys):
    t, home = setup(tmp_path)
    completer(home, "_dfctl")
    cache = dump(home)

    def refuse(self, *args, **kwargs):
        raise PermissionError("denied")

    monkeypatch.setattr(Path, "unlink", refuse)
    assert zsh_cache.refresh_zsh_completion_cache(t)
    assert "delete ~/.zcompdump* by hand" in capsys.readouterr().out
    assert not (home / STORE).exists()
    monkeypatch.undo()
    zsh_cache.refresh_zsh_completion_cache(t)
    assert not cache.exists()


def test_a_fingerprint_that_cannot_be_recorded_warns_instead_of_failing_the_install(tmp_path, capsys):
    t, home = setup(tmp_path)
    completer(home, "_dfctl")
    cache = dump(home)
    (home / ".local/state").mkdir(parents=True)
    (home / ".local/state/dotfiles").write_text("a file where the directory should be")
    assert zsh_cache.refresh_zsh_completion_cache(t)
    assert "Could not record the zsh completion fingerprint" in capsys.readouterr().out
    assert not cache.exists()


def test_nothing_is_claimed_removed_when_there_was_no_dump(tmp_path, capsys):
    t, home = setup(tmp_path)
    completer(home, "_dfctl")
    zsh_cache.refresh_zsh_completion_cache(t)
    assert "Removed zsh's completion cache" not in capsys.readouterr().out
    assert stored(home) == zsh_cache.fingerprint(home)
