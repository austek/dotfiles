import json

import pytest
from dotfiles_setup.presets import Preset, load_preset, resolve_packages


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
    preset = load_preset(tmp_path, "work")
    assert preset == Preset(
        name="work",
        description="Work machine",
        package_files=("apt_common.txt", "apt_work.txt"),
        backend_overrides={"apt": {"bat": "batcat"}},
        claude_settings="claude_work.json",
    )


def test_load_preset_defaults_missing_optional_fields(tmp_path):
    _write_manifest(tmp_path, "minimal", package_files=["apt_common.txt"])
    preset = load_preset(tmp_path, "minimal")
    assert preset.description == ""
    assert preset.backend_overrides == {}
    assert preset.claude_settings is None


def test_load_preset_raises_for_unknown_name(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_preset(tmp_path, "nonexistent")


def test_resolve_packages_dedupes_and_sorts_across_files(tmp_path):
    (tmp_path / "common.txt").write_text("zsh\ncurl\n# comment\n\n")
    (tmp_path / "extra.txt").write_text("curl\nripgrep\n")
    preset = Preset(
        name="x", description="", package_files=("common.txt", "extra.txt"),
        backend_overrides={}, claude_settings=None,
    )
    assert resolve_packages(tmp_path, preset) == ("curl", "ripgrep", "zsh")


def test_resolve_packages_skips_missing_files(tmp_path):
    (tmp_path / "common.txt").write_text("zsh\n")
    preset = Preset(
        name="x", description="", package_files=("common.txt", "nonexistent.txt"),
        backend_overrides={}, claude_settings=None,
    )
    assert resolve_packages(tmp_path, preset) == ("zsh",)
