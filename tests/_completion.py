import subprocess
from pathlib import Path

_COMPLETIONS = Path(__file__).resolve().parent.parent / "bash" / ".local" / "share" / "bash-completion" / "completions"


def complete(command: str, function: str, words: list[str], cword: int) -> list[str]:
    comp_words = " ".join(f'"{w}"' for w in words)
    script = f'''
source "{_COMPLETIONS / command}"
COMP_WORDS=({comp_words})
COMP_CWORD={cword}
{function}
printf '%s\\n' "${{COMPREPLY[@]}}"
'''
    result = subprocess.run(["bash", "-c", script], capture_output=True, text=True, check=True)
    return [line for line in result.stdout.splitlines() if line]
