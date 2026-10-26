from _completion import complete


def _complete(words: list[str], cword: int) -> list[str]:
    return complete("dotfiles-backup", "_dotfiles_backup_completions", words, cword)


def test_completes_save_subcommand_by_prefix():
    completions = _complete(["dotfiles-backup", "sa"], 1)
    assert completions == ["save"]


def test_completes_all_candidates_for_bare_dash():
    completions = _complete(["dotfiles-backup", ""], 1)
    assert set(completions) == {"save", "-h", "--help"}
