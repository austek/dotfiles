import subprocess
from pathlib import Path

COMPLETION_SCRIPT = (
    Path(__file__).resolve().parent.parent
    / "bash" / ".local" / "share" / "bash-completion" / "completions" / "dotfiles-backup"
)


def _complete(words: list[str], cword: int) -> list[str]:
    comp_words = " ".join(f'"{w}"' for w in words)
    script = f'''
source "{COMPLETION_SCRIPT}"
COMP_WORDS=({comp_words})
COMP_CWORD={cword}
_dotfiles_backup_completions
printf '%s\\n' "${{COMPREPLY[@]}}"
'''
    result = subprocess.run(
        ["bash", "-c", script], capture_output=True, text=True, check=True
    )
    return [line for line in result.stdout.splitlines() if line]


def test_completes_save_subcommand_by_prefix():
    completions = _complete(["dotfiles-backup", "sa"], 1)
    assert completions == ["save"]


def test_completes_all_candidates_for_bare_dash():
    completions = _complete(["dotfiles-backup", ""], 1)
    assert set(completions) == {"save", "-h", "--help"}
