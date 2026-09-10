import subprocess
from pathlib import Path

COMPLETION_SCRIPT = (
    Path(__file__).resolve().parent.parent
    / "bash" / ".local" / "share" / "bash-completion" / "completions" / "dotfiles-setup"
)


def _complete(words: list[str], cword: int) -> list[str]:
    comp_words = " ".join(f'"{w}"' for w in words)
    script = f'''
source "{COMPLETION_SCRIPT}"
COMP_WORDS=({comp_words})
COMP_CWORD={cword}
_dotfiles_setup_completions
printf '%s\\n' "${{COMPREPLY[@]}}"
'''
    result = subprocess.run(
        ["bash", "-c", script], capture_output=True, text=True, check=True
    )
    return [line for line in result.stdout.splitlines() if line]


def test_completes_install_subcommand_by_prefix():
    completions = _complete(["dotfiles-setup", "ins"], 1)
    assert completions == ["install"]


def test_completes_long_options_by_prefix():
    completions = _complete(["dotfiles-setup", "install", "--pre"], 2)
    assert completions == ["--preset"]


def test_completes_preset_values_after_preset_flag():
    completions = _complete(["dotfiles-setup", "install", "--preset", ""], 3)
    assert set(completions) == {"work", "personal", "homelab"}


def test_completes_nothing_unexpected_for_bare_dash():
    completions = _complete(["dotfiles-setup", "install", "-"], 2)
    assert set(completions) == {"-v", "--verbose", "-vv", "-vvv", "-h", "--help", "--preset", "--dry-run"}
