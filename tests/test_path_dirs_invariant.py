import json
from pathlib import Path

from dotfiles_setup import foothold, path_dirs, stale_copies, tools
from dotfiles_setup.log import Logger
from dotfiles_setup.release_installers import SYSTEM_BIN_DIR, user_bin_dir
from dotfiles_setup.result import Ok
from dotfiles_setup.user_links import USER_LINKS

ROOT = Path(__file__).resolve().parent.parent


def _list_entries() -> tuple[str, ...]:
    result = path_dirs.load(ROOT, None)
    assert isinstance(result, Ok), result
    return result.value


def _as_entry(directory: Path, home: Path) -> str:
    return f"~/{directory.relative_to(home)}" if directory.is_relative_to(home) else str(directory)


def _tooling(home: Path) -> tools.Tooling:
    return tools.Tooling(Logger(dry_run=False, verbosity=0), home)


def test_the_user_bin_dir_dfctl_installs_into_is_on_the_list(tmp_path):
    assert _as_entry(user_bin_dir(_tooling(tmp_path)), tmp_path) in _list_entries()


def test_every_directory_the_stale_copy_check_searches_is_on_the_list(tmp_path):
    searched = stale_copies.search_dirs(_tooling(tmp_path))
    assert {_as_entry(directory, tmp_path) for directory in searched} <= set(_list_entries())


def test_the_system_bin_dir_dfctl_may_install_into_is_on_the_list():
    assert str(SYSTEM_BIN_DIR) in _list_entries()


def test_every_tool_dfctl_links_into_the_user_bin_dir_is_reachable_through_a_listed_directory(tmp_path):
    link_dir = _as_entry(user_bin_dir(_tooling(tmp_path)), tmp_path)
    assert USER_LINKS
    assert link_dir in _list_entries()


def test_the_foothold_module_keeps_no_path_list_of_its_own():
    assert not hasattr(foothold, "PATH_DIRS")


def test_the_base_claude_settings_keep_no_path_of_their_own():
    settings = json.loads((ROOT / "claude" / ".claude" / "settings.json").read_text())
    assert "PATH" not in settings.get("env", {})
