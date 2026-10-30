import json

from dotfiles_setup.overlay import (
    find_overlay_root,
    load_preset_settings,
    merge_settings,
    overlay_package_names,
)


def test_find_overlay_root_none_when_nothing_present(tmp_path, monkeypatch):
    monkeypatch.delenv("DOTFILES_PRIVATE_ROOT", raising=False)
    monkeypatch.setattr("dotfiles_setup.overlay.DEFAULT_OVERLAY_ROOT", tmp_path / "missing")
    monkeypatch.setattr("dotfiles_setup.overlay.LOCAL_OVERLAY_ROOT", tmp_path / "also-missing")
    assert find_overlay_root() is None


def test_find_overlay_root_prefers_env_override(tmp_path, monkeypatch):
    override = tmp_path / "custom-private"
    override.mkdir()
    monkeypatch.setenv("DOTFILES_PRIVATE_ROOT", str(override))
    assert find_overlay_root() == override


def test_find_overlay_root_falls_back_to_default_sibling(tmp_path, monkeypatch):
    monkeypatch.delenv("DOTFILES_PRIVATE_ROOT", raising=False)
    default_root = tmp_path / "dotfiles-private"
    default_root.mkdir()
    monkeypatch.setattr("dotfiles_setup.overlay.DEFAULT_OVERLAY_ROOT", default_root)
    assert find_overlay_root() == default_root


def test_overlay_package_names_empty_without_overlay_root():
    assert overlay_package_names(None, "work") == ()


def test_overlay_package_names_empty_without_matching_fragment(tmp_path):
    assert overlay_package_names(tmp_path, "work") == ()


def test_overlay_package_names_reads_and_dedupes(tmp_path):
    frag_dir = tmp_path / "packages"
    frag_dir.mkdir()
    (frag_dir / "work_extra.txt").write_text("kubectl\n# comment\nkubectl\ndocker-cli\n")
    assert overlay_package_names(tmp_path, "work") == ("docker-cli", "kubectl")


def test_merge_settings_unions_lists_keeping_base_order():
    base = {"permissions": {"allow": ["a", "b"]}}
    overlay = {"permissions": {"allow": ["b", "c"]}}
    assert merge_settings(base, overlay) == {"permissions": {"allow": ["a", "b", "c"]}}


def test_merge_settings_overlay_scalar_wins():
    assert merge_settings({"x": 1}, {"x": 2}) == {"x": 2}


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))
    return path


def test_preset_settings_are_the_base_without_a_profile_or_overlay(tmp_path):
    base = write_json(tmp_path / "base.json", {"a": 1})
    assert load_preset_settings(base, None, None, "work") == {"a": 1}
    assert load_preset_settings(base, tmp_path / "missing.json", tmp_path, "work") == {"a": 1}


def test_preset_settings_merge_the_profile_over_the_base(tmp_path):
    base = write_json(tmp_path / "base.json", {"enabledPlugins": {"a": True}, "permissions": {"allow": ["x"]}})
    profile = write_json(tmp_path / "profile.json", {"enabledPlugins": {"b": True}, "permissions": {"allow": ["y"]}})
    merged = load_preset_settings(base, profile, None, "work")
    assert merged == {"enabledPlugins": {"a": True, "b": True}, "permissions": {"allow": ["x", "y"]}}


def test_preset_settings_apply_the_overlay_settings_then_its_preset_file(tmp_path):
    base = write_json(tmp_path / "base.json", {"model": "base", "enabledPlugins": {"a": True}})
    profile = write_json(tmp_path / "profile.json", {"model": "profile"})
    overlay = tmp_path / "priv"
    write_json(overlay / "claude-settings" / "settings.json", {"model": "overlay", "enabledPlugins": {"b": True}})
    write_json(overlay / "claude-profiles" / "work.json", {"model": "overlay-work", "enabledPlugins": {"c": True}})
    merged = load_preset_settings(base, profile, overlay, "work")
    assert merged == {"model": "overlay-work", "enabledPlugins": {"a": True, "b": True, "c": True}}


def test_preset_settings_skip_another_presets_overlay_file(tmp_path):
    base = write_json(tmp_path / "base.json", {"enabledPlugins": {}})
    overlay = tmp_path / "priv"
    write_json(overlay / "claude-profiles" / "work.json", {"enabledPlugins": {"collibra": True}})
    assert load_preset_settings(base, None, overlay, "homelab") == {"enabledPlugins": {}}


def test_merge_settings_deduplicates_repeats_within_the_overlay_list():
    assert merge_settings({"allow": ["a"]}, {"allow": ["b", "b"]}) == {"allow": ["a", "b"]}
