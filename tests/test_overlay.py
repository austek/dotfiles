import json
from pathlib import Path

import pytest
from dotfiles_setup.overlay import (
    expand_home_in_env,
    find_overlay_root,
    load_preset_settings,
    merge_settings,
    overlay_package_names,
)


@pytest.fixture
def roots(tmp_path, monkeypatch):
    """Points every overlay location at a missing path under tmp_path and clears both override variables."""
    for variable in ("DOTFILES_OVERLAY_ROOT", "DOTFILES_PRIVATE_ROOT"):
        monkeypatch.delenv(variable, raising=False)
    found = {name: tmp_path / name for name in ("overlay", "legacy", "local")}
    monkeypatch.setattr("dotfiles_setup.overlay.DEFAULT_OVERLAY_ROOT", found["overlay"])
    monkeypatch.setattr("dotfiles_setup.overlay.LEGACY_OVERLAY_ROOT", found["legacy"])
    monkeypatch.setattr("dotfiles_setup.overlay.LOCAL_OVERLAY_ROOT", found["local"])
    return found


def test_find_overlay_root_none_when_nothing_present(roots):
    assert find_overlay_root() is None


def test_find_overlay_root_prefers_env_override(roots, tmp_path, monkeypatch):
    override = tmp_path / "custom-overlay"
    override.mkdir()
    roots["overlay"].mkdir()
    monkeypatch.setenv("DOTFILES_OVERLAY_ROOT", str(override))
    assert find_overlay_root() == override


def test_find_overlay_root_still_honours_the_legacy_override_variable(roots, tmp_path, monkeypatch):
    override = tmp_path / "custom-private"
    override.mkdir()
    monkeypatch.setenv("DOTFILES_PRIVATE_ROOT", str(override))
    assert find_overlay_root() == override


def test_the_overlay_variable_wins_over_the_legacy_one(roots, tmp_path, monkeypatch):
    new, old = tmp_path / "new", tmp_path / "old"
    new.mkdir()
    old.mkdir()
    monkeypatch.setenv("DOTFILES_OVERLAY_ROOT", str(new))
    monkeypatch.setenv("DOTFILES_PRIVATE_ROOT", str(old))
    assert find_overlay_root() == new


def test_an_override_that_does_not_exist_means_no_overlay_not_a_fallback(roots, tmp_path, monkeypatch):
    roots["overlay"].mkdir()
    monkeypatch.setenv("DOTFILES_OVERLAY_ROOT", str(tmp_path / "missing"))
    assert find_overlay_root() is None


def test_find_overlay_root_falls_back_to_default_sibling(roots):
    roots["overlay"].mkdir()
    assert find_overlay_root() == roots["overlay"]


def test_find_overlay_root_falls_back_to_the_legacy_private_checkout(roots):
    roots["legacy"].mkdir()
    assert find_overlay_root() == roots["legacy"]


def test_the_overlay_checkout_wins_over_the_legacy_one(roots):
    roots["overlay"].mkdir()
    roots["legacy"].mkdir()
    assert find_overlay_root() == roots["overlay"]


def test_the_local_overlay_is_the_last_resort(roots):
    roots["local"].mkdir()
    assert find_overlay_root() == roots["local"]
    roots["legacy"].mkdir()
    assert find_overlay_root() == roots["legacy"]


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


HOME = Path("/h/me")


@pytest.mark.parametrize(("raw", "expanded"), [
    ("$HOME/bin:/usr/bin", "/h/me/bin:/usr/bin"),
    ("${HOME}/a:$HOME/b", "/h/me/a:/h/me/b"),
    ("~/.local/bin", "/h/me/.local/bin"),
    ("~", "/h/me"),
    ("$HOMEDIR/x", "$HOMEDIR/x"),
    ("/opt/~/x", "/opt/~/x"),
])
def test_expand_home_in_env_rewrites_home_references(raw, expanded):
    assert expand_home_in_env({"env": {"PATH": raw}}, HOME) == {"env": {"PATH": expanded}}


def test_expand_home_in_env_leaves_non_env_keys_and_non_strings_alone():
    hooks = {"Stop": [{"hooks": [{"command": "\"$HOME/x.sh\""}]}]}
    settings = {"env": {"N": 1, "P": "$HOME"}, "hooks": hooks, "model": "$HOME"}
    assert expand_home_in_env(settings, HOME) == {"env": {"N": 1, "P": "/h/me"}, "hooks": hooks, "model": "$HOME"}


def test_expand_home_in_env_does_not_mutate_its_input():
    settings = {"env": {"PATH": "$HOME/bin"}}
    expand_home_in_env(settings, HOME)
    assert settings == {"env": {"PATH": "$HOME/bin"}}


def test_expand_home_in_env_returns_settings_without_env_unchanged():
    assert expand_home_in_env({"model": "x"}, HOME) == {"model": "x"}
