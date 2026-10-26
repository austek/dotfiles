import json

from dotfiles_setup.presets import Preset, load_preset, package_names, resolve_packages
from dotfiles_setup.result import Err, Ok


def test_package_names_drops_comments_blanks_and_whitespace():
    assert package_names("# c\n\n  git \nzsh\n") == {"git", "zsh"}


def test_load_preset_rejects_path_traversal(tmp_path):
    (tmp_path / "x.json").write_text("{}")
    assert isinstance(load_preset(tmp_path / "presets", "../x"), Err)


def _write_manifest(dir_, name, **fields):
    (dir_ / f"{name}.json").write_text(json.dumps(fields))


def test_load_preset_reads_all_fields(tmp_path):
    _write_manifest(
        tmp_path, "work",
        description="Work machine",
        package_files=["apt_common.txt", "apt_work.txt"],
        backend_overrides={"apt": {"bat": "batcat"}},
        claude_settings="claude_work.json",
    )
    preset = load_preset(tmp_path, "work").value
    assert preset == Preset(
        name="work",
        description="Work machine",
        package_files=("apt_common.txt", "apt_work.txt"),
        backend_overrides={"apt": {"bat": "batcat"}},
        claude_settings="claude_work.json",
    )


def test_load_preset_defaults_missing_optional_fields(tmp_path):
    _write_manifest(tmp_path, "minimal", package_files=["apt_common.txt"])
    preset = load_preset(tmp_path, "minimal").value
    assert preset.description == ""
    assert preset.backend_overrides == {}
    assert preset.claude_settings is None


def test_load_preset_returns_err_for_unknown_name(tmp_path):
    assert load_preset(tmp_path, "nonexistent") == Err(f"No preset named 'nonexistent' in {tmp_path}")


def test_resolve_packages_dedupes_and_sorts_across_files(tmp_path):
    (tmp_path / "common.txt").write_text("zsh\ncurl\n# comment\n\n")
    (tmp_path / "extra.txt").write_text("curl\nripgrep\n")
    preset = Preset(
        name="x", description="", package_files=("common.txt", "extra.txt"),
        backend_overrides={}, claude_settings=None,
    )
    assert resolve_packages(tmp_path, preset) == Ok(("curl", "ripgrep", "zsh"))


def test_resolve_packages_returns_err_for_missing_files(tmp_path):
    (tmp_path / "common.txt").write_text("zsh\n")
    preset = Preset(
        name="x", description="", package_files=("common.txt", "nonexistent.txt"),
        backend_overrides={}, claude_settings=None,
    )
    assert resolve_packages(tmp_path, preset) == Err(
        f"Preset 'x' declares missing package file: {tmp_path / 'nonexistent.txt'}"
    )
