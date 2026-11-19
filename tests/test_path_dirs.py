from pathlib import Path

from dotfiles_setup import path_dirs
from dotfiles_setup.result import Err, Ok


def _unwrap(result):
    assert isinstance(result, Ok), result
    return result.value


def _write_base(dotfiles: Path, text: str) -> None:
    (dotfiles / "packages").mkdir(parents=True, exist_ok=True)
    (dotfiles / "packages" / "path_dirs.txt").write_text(text)


def _write_extras(overlay_root: Path, text: str) -> None:
    (overlay_root / "packages").mkdir(parents=True, exist_ok=True)
    (overlay_root / "packages" / "path_dirs_extra.txt").write_text(text)


def test_parse_ignores_comments_and_blank_lines():
    assert _unwrap(path_dirs.parse("# header\n\n~/a\n  \n# note\n/usr/bin\n")) == ("~/a", "/usr/bin")


def test_parse_keeps_the_first_duplicate_in_order():
    assert _unwrap(path_dirs.parse("~/a\n/usr/bin\n~/a\n/bin\n/usr/bin\n")) == ("~/a", "/usr/bin", "/bin")


def test_parse_rejects_a_relative_entry_naming_its_line():
    result = path_dirs.parse("~/a\nbin\n")
    assert isinstance(result, Err)
    assert "line 2" in result.error


def test_parse_trims_whitespace_around_an_entry():
    assert _unwrap(path_dirs.parse("  ~/a  \n")) == ("~/a",)


def test_load_appends_the_overlay_extras_after_the_base(tmp_path):
    dotfiles, overlay_root = tmp_path / "dotfiles", tmp_path / "overlay"
    _write_base(dotfiles, "~/a\n/usr/bin\n")
    _write_extras(overlay_root, "~/org/bin\n~/a\n")
    assert _unwrap(path_dirs.load(dotfiles, overlay_root)) == ("~/a", "/usr/bin", "~/org/bin")


def test_load_without_an_extras_file_returns_the_base(tmp_path):
    dotfiles, overlay_root = tmp_path / "dotfiles", tmp_path / "overlay"
    _write_base(dotfiles, "~/a\n")
    overlay_root.mkdir()
    assert _unwrap(path_dirs.load(dotfiles, overlay_root)) == ("~/a",)


def test_load_without_an_overlay_returns_the_base(tmp_path):
    _write_base(tmp_path, "~/a\n")
    assert _unwrap(path_dirs.load(tmp_path, None)) == ("~/a",)


def test_load_with_a_missing_base_file_is_an_error(tmp_path):
    assert isinstance(path_dirs.load(tmp_path, None), Err)


def test_load_names_the_file_of_a_malformed_extras_entry(tmp_path):
    dotfiles, overlay_root = tmp_path / "dotfiles", tmp_path / "overlay"
    _write_base(dotfiles, "~/a\n")
    _write_extras(overlay_root, "relative\n")
    result = path_dirs.load(dotfiles, overlay_root)
    assert isinstance(result, Err)
    assert "path_dirs_extra.txt" in result.error
    assert "line 1" in result.error


def test_for_env_expands_the_tilde_to_home(tmp_path):
    assert path_dirs.for_env(("~/.local/bin", "/usr/bin"), tmp_path) == f"{tmp_path}/.local/bin:/usr/bin"


def test_for_systemd_maps_the_tilde_to_percent_h_and_leaves_absolute_paths():
    assert path_dirs.for_systemd(("~/.local/bin", "/usr/bin")) == ("%h/.local/bin", "/usr/bin")
