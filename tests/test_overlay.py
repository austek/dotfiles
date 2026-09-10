import json

from dotfiles_setup.overlay import (
    find_overlay_root,
    load_claude_settings,
    merge_claude_settings,
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


def test_merge_claude_settings_shallow_overlay_wins():
    base = {"a": 1, "b": 2}
    overlay = {"b": 3, "c": 4}
    assert merge_claude_settings(base, overlay) == {"a": 1, "b": 3, "c": 4}


def test_merge_claude_settings_deep_merges_nested_dicts():
    base = {"hooks": {"PreToolUse": {"x": 1}}}
    overlay = {"hooks": {"PreToolUse": {"y": 2}}}
    assert merge_claude_settings(base, overlay) == {"hooks": {"PreToolUse": {"x": 1, "y": 2}}}


def test_merge_claude_settings_none_overlay_returns_base_unchanged():
    base = {"a": 1}
    assert merge_claude_settings(base, None) == base


def test_load_claude_settings_merges_base_and_overlay(tmp_path):
    base_path = tmp_path / "base.json"
    base_path.write_text(json.dumps({"enabledPlugins": {"x": True}}))
    overlay_root = tmp_path / "priv"
    (overlay_root / "claude-profiles").mkdir(parents=True)
    (overlay_root / "claude-profiles" / "work.json").write_text(
        json.dumps({"enabledPlugins": {"y": True}})
    )
    merged = load_claude_settings(base_path, overlay_root, "work")
    assert merged == {"enabledPlugins": {"x": True, "y": True}}


def test_load_claude_settings_base_only_when_no_overlay(tmp_path):
    base_path = tmp_path / "base.json"
    base_path.write_text(json.dumps({"enabledPlugins": {"x": True}}))
    assert load_claude_settings(base_path, None, "work") == {"enabledPlugins": {"x": True}}


def test_load_claude_settings_empty_dict_when_base_missing(tmp_path):
    assert load_claude_settings(tmp_path / "nonexistent.json", None, "work") == {}
