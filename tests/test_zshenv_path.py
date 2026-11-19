import shutil
import subprocess
from pathlib import Path

import pytest
from dotfiles_setup import path_dirs, stale_copies, tools
from dotfiles_setup.log import Logger
from dotfiles_setup.release_installers import SYSTEM_BIN_DIR

REPO = Path(__file__).parent.parent
ZSHENV = REPO / "zsh" / ".zshenv"
REAL_LIST = REPO / "packages" / "path_dirs.txt"
INHERITED = ["/usr/local/bin", "/usr/bin", "/bin"]

pytestmark = pytest.mark.skipif(shutil.which("zsh") is None, reason="zsh is not installed")


def resolved_path(
    home: Path, existing: list[str], *, base: str | None = None, extras: str | None = None,
    inherited_under_home: list[str] = (), no_list: bool = False, extras_root: str | None = None,
    cwd: Path | None = None,
) -> list[str]:
    """`base` defaults to the repo's real list; `no_list` leaves the file absent; `extras` lands in the overlay.

    `extras_root` is a home-relative overlay directory found by lookup (no variable); without it the
    overlay is `org-overlay`, named through DOTFILES_OVERLAY_ROOT.
    """
    for relative in existing:
        (home / relative).mkdir(parents=True, exist_ok=True)
    env = {"HOME": str(home), "ZDOTDIR": str(home)}
    env["PATH"] = ":".join([*(str(home / relative) for relative in inherited_under_home), *INHERITED])
    if not no_list:
        listing = home / ".dotfiles" / "packages" / "path_dirs.txt"
        listing.parent.mkdir(parents=True, exist_ok=True)
        listing.write_text(REAL_LIST.read_text() if base is None else base)
    if extras is not None:
        overlay_root = home / (extras_root or "org-overlay")
        (overlay_root / "packages").mkdir(parents=True, exist_ok=True)
        (overlay_root / "packages" / "path_dirs_extra.txt").write_text(extras)
        if extras_root is None:
            env["DOTFILES_OVERLAY_ROOT"] = str(overlay_root)
    result = subprocess.run(
        ["zsh", "-f", "-c", f'. "{ZSHENV}"; print -l -- $path'],
        env=env, capture_output=True, text=True, check=True, cwd=cwd or home,
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


def test_zshenv_path_follows_the_file_order(tmp_path):
    path = resolved_path(tmp_path, ["a", "b", "c"], base="~/c\n~/a\n~/b\n")
    assert path[:3] == ["~/c", "~/a", "~/b"]


def test_zshenv_appends_the_overlay_extras_after_the_base(tmp_path):
    path = resolved_path(tmp_path, ["a", "org"], base="~/a\n", extras="# org\n~/org\n")
    assert path[:2] == ["~/a", "~/org"]


def test_zshenv_drops_listed_directories_that_do_not_exist(tmp_path):
    path = resolved_path(tmp_path, ["a"], base="~/a\n~/missing\n/no/such/dir\n")
    assert "~/missing" not in path
    assert "/no/such/dir" not in path


def test_zshenv_ignores_comments_and_blank_lines_in_the_file(tmp_path):
    path = resolved_path(tmp_path, ["a"], base="# header\n\n  \n~/a\n")
    assert path[0] == "~/a"
    assert not any(entry.startswith("#") for entry in path)


def test_an_inherited_sdkman_java_version_beats_the_files_current_entry(tmp_path):
    path = resolved_path(
        tmp_path,
        [".sdkman/candidates/java/17/bin", ".sdkman/candidates/java/current/bin", ".sdkman/candidates/gradle/current/bin"],
        base="~/.sdkman/candidates/java/current/bin\n~/.sdkman/candidates/gradle/current/bin\n",
        inherited_under_home=[".sdkman/candidates/java/17/bin"],
    )
    assert "~/.sdkman/candidates/java/17/bin" in path
    assert "~/.sdkman/candidates/java/current/bin" not in path
    assert "~/.sdkman/candidates/gradle/current/bin" in path


def test_inherited_prepends_stay_ahead_of_the_system_directories_with_the_real_list(tmp_path):
    path = resolved_path(
        tmp_path, [".venv/bin", ".nvm/versions/node/v18/bin", ".sdkman/candidates/java/17/bin"],
        inherited_under_home=[".venv/bin", ".nvm/versions/node/v18/bin", ".sdkman/candidates/java/17/bin"],
    )
    for inherited in ("~/.venv/bin", "~/.nvm/versions/node/v18/bin", "~/.sdkman/candidates/java/17/bin"):
        assert path.index(inherited) < path.index("/usr/bin")


def test_an_inherited_sdkman_current_dir_stays_ahead_of_the_system_directories(tmp_path):
    path = resolved_path(
        tmp_path, [".sdkman/candidates/java/current/bin"], inherited_under_home=[".sdkman/candidates/java/current/bin"],
    )
    assert path.count("~/.sdkman/candidates/java/current/bin") == 1
    assert path.index("~/.sdkman/candidates/java/current/bin") < path.index("/usr/bin")


def test_the_user_dirs_still_precede_inherited_prepends(tmp_path):
    path = resolved_path(tmp_path, [".venv/bin", ".local/bin"], inherited_under_home=[".venv/bin"])
    assert path.index("~/.local/bin") < path.index("~/.venv/bin")


def test_zshenv_skips_a_relative_extras_entry(tmp_path):
    workdir = tmp_path / "work"
    (workdir / "bin").mkdir(parents=True)
    path = resolved_path(tmp_path, ["a"], base="~/a\n", extras="bin\n./bin\n", cwd=workdir)
    assert "bin" not in path
    assert "./bin" not in path


def test_zshenv_finds_extras_in_a_legacy_overlay_root(tmp_path):
    path = resolved_path(tmp_path, ["a", "org"], base="~/a\n", extras="~/org\n", extras_root=".dotfiles-private")
    assert path[:2] == ["~/a", "~/org"]


def test_zshenv_finds_extras_in_the_local_overlay_root(tmp_path):
    path = resolved_path(
        tmp_path, ["a", "org"], base="~/a\n", extras="~/org\n", extras_root=".config/dotfiles/local-overlay",
    )
    assert path[:2] == ["~/a", "~/org"]


def test_an_unreadable_base_file_keeps_the_fallback_dirs_when_extras_exist(tmp_path):
    path = resolved_path(tmp_path, [".local/bin", "org"], no_list=True, extras="~/org\n", extras_root=".dotfiles-overlay")
    assert "~/.local/bin" in path
    assert "~/org" in path


def test_the_shell_claude_and_foothold_paths_agree_on_the_real_list(tmp_path):
    entries = path_dirs.load(REPO, None).value
    home_dirs = [entry[2:] for entry in entries if entry.startswith("~/")]
    shell = resolved_path(tmp_path, home_dirs)
    expanded = path_dirs.for_env(entries, tmp_path).split(":")
    systemd = [entry.replace("%h", str(tmp_path)) for entry in path_dirs.for_systemd(entries)]
    assert expanded == systemd
    existing = [entry.replace(str(tmp_path), "~") for entry in expanded if Path(entry).is_dir()]
    assert shell == existing


def test_zshenv_falls_back_to_the_base_dirs_when_the_file_is_unreadable(tmp_path):
    path = resolved_path(tmp_path, [".local/bin", ".dotfiles/bin"], no_list=True)
    assert path[:2] == ["~/.dotfiles/bin", "~/.local/bin"]
    assert "/usr/bin" in path
