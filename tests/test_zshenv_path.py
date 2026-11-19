import shutil
import subprocess
from pathlib import Path

import pytest
from dotfiles_setup import stale_copies, tools
from dotfiles_setup.log import Logger
from dotfiles_setup.release_installers import SYSTEM_BIN_DIR

ZSHENV = Path(__file__).parent.parent / "zsh" / ".zshenv"
INHERITED = ["/usr/local/bin", "/usr/bin", "/bin"]

pytestmark = pytest.mark.skipif(shutil.which("zsh") is None, reason="zsh is not installed")


def resolved_path(home: Path, existing: list[str]) -> list[str]:
    for relative in existing:
        (home / relative).mkdir(parents=True, exist_ok=True)
    env = {"HOME": str(home), "PATH": ":".join(INHERITED), "ZDOTDIR": str(home)}
    result = subprocess.run(
        ["zsh", "-f", "-c", f'. "{ZSHENV}"; print -l -- $path'],
        env=env, capture_output=True, text=True, check=True,
    )
    return [line.replace(str(home), "~") for line in result.stdout.splitlines()]


EVERY_DIR = [
    ".local/share/sonarqube-cli/bin", ".local/share/JetBrains/Toolbox/bin", ".local/share/JetBrains/Toolbox/scripts",
    ".local/bin", "bin", ".dotfiles/bin",
]


def test_the_user_bin_dirs_precede_the_inherited_path_in_the_order_the_stale_copy_check_assumes(tmp_path):
    path = resolved_path(tmp_path, EVERY_DIR)
    expected = [d.as_posix().replace(str(tmp_path), "~") for d in stale_copies.search_dirs(
        tools.Tooling(Logger(dry_run=False, verbosity=0), tmp_path),
    )]
    assert [entry for entry in path if entry in expected] == expected
    assert expected[-1] == SYSTEM_BIN_DIR.as_posix()


def test_the_single_tool_bin_dirs_are_not_on_path_but_the_toolbox_scripts_dir_is(tmp_path):
    path = resolved_path(tmp_path, EVERY_DIR)
    assert "~/.local/share/sonarqube-cli/bin" not in path
    assert "~/.local/share/JetBrains/Toolbox/bin" not in path
    assert "~/.local/share/JetBrains/Toolbox/scripts" in path
