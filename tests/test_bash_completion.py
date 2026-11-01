from _completion import complete


def _complete(words: list[str], cword: int) -> list[str]:
    return complete("dotfiles-setup", "_dotfiles_setup_completions", words, cword)


def test_completes_install_subcommand_by_prefix():
    completions = _complete(["dotfiles-setup", "ins"], 1)
    assert completions == ["install"]


def test_completes_long_options_by_prefix():
    completions = _complete(["dotfiles-setup", "install", "--pre"], 2)
    assert completions == ["--preset"]


def test_completes_preset_values_after_preset_flag():
    completions = _complete(["dotfiles-setup", "install", "--preset", ""], 3)
    assert set(completions) == {"work", "personal", "homelab"}


def test_completes_private_clone_subcommand_and_options():
    assert _complete(["dotfiles-setup", "pri"], 1) == ["private"]
    assert _complete(["dotfiles-setup", "private", "cl"], 2) == ["clone"]
    assert "--repo" in _complete(["dotfiles-setup", "private", "clone", "--"], 3)


def test_completes_preset_equals_form():
    completions = _complete(["dotfiles-setup", "install", "--preset=wo"], 2)
    assert completions == ["--preset=work"]


def test_completes_preset_when_bash_splits_the_equals_sign():
    assert _complete(["dotfiles-setup", "install", "--preset", "=", "wo"], 4) == ["work"]
    assert sorted(_complete(["dotfiles-setup", "install", "--preset", "="], 3)) == ["homelab", "personal", "work"]


def test_omits_the_opposite_system_flag_once_one_is_typed():
    after_system = _complete(["dotfiles-setup", "install", "--system", "--"], 3)
    after_no_system = _complete(["dotfiles-setup", "install", "--no-system", "--"], 3)
    assert "--system" in after_system
    assert "--no-system" not in after_system
    assert "--no-system" in after_no_system
    assert "--system" not in after_no_system


def test_keeps_both_system_flags_when_the_text_sits_inside_one_quoted_word():
    words = ["dotfiles-setup", "install", "--preset", "team --system notes", "--"]
    offered = _complete(words, 4)
    assert "--system" in offered
    assert "--no-system" in offered


def test_completes_nothing_unexpected_for_bare_dash():
    completions = _complete(["dotfiles-setup", "install", "-"], 2)
    assert set(completions) == {"-v", "--verbose", "-vv", "-vvv", "-h", "--help", "--preset", "--dry-run", "--reconfigure", "--force", "--accept-drift", "--system", "--no-system"}
