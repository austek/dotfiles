import os
from types import SimpleNamespace

import pytest
from dotfiles_setup import (
    claude_profile,
    desktop_defaults,
    release_installers,
    secrets_env,
    stow,
    tools,
    user_links,
    zsh_cache,
)
from dotfiles_setup.log import Logger
from dotfiles_setup.rollback import RollbackLog
from dotfiles_setup.tooling import Tooling


def _t(home, run=None):
    return Tooling(Logger(dry_run=False), home, run=run) if run else Tooling(Logger(dry_run=False), home)


def _stow_plan(tmp_path, overlay=False, preset="work"):
    home, repo = tmp_path / "home", tmp_path / "repo"
    home.mkdir(exist_ok=True)
    repo.mkdir(exist_ok=True)
    root = tmp_path / "overlay" if overlay else None
    if root:
        root.mkdir(exist_ok=True)
    return stow.StowPlan(_t(home), repo, root, False, tmp_path / "bk", "s", RollbackLog(tmp_path / "log"), preset)


def _package(root, name, files):
    for rel in files:
        path = root / name / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(rel)


def _link(plan, name, rel, root=None):
    target = plan.t.home / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.symlink_to((root or plan.dotfiles_dir) / name / rel)


def test_stow_reports_a_public_package_that_is_not_linked(tmp_path):
    plan = _stow_plan(tmp_path)
    (plan.dotfiles_dir / ".stow-packages").write_text("zsh\n")
    _package(plan.dotfiles_dir, "zsh", [".zshrc"])
    assert stow.pending_links(plan) == ("link zsh",)


def test_stow_reports_nothing_once_every_file_is_linked(tmp_path):
    plan = _stow_plan(tmp_path)
    (plan.dotfiles_dir / ".stow-packages").write_text("zsh\n")
    _package(plan.dotfiles_dir, "zsh", [".zshrc", ".config/zsh/a"])
    _link(plan, "zsh", ".zshrc")
    _link(plan, "zsh", ".config/zsh/a")
    assert stow.pending_links(plan) == ()


def test_stow_notices_a_new_file_in_an_already_linked_package(tmp_path):
    plan = _stow_plan(tmp_path)
    (plan.dotfiles_dir / ".stow-packages").write_text("zsh\n")
    _package(plan.dotfiles_dir, "zsh", [".zshrc", ".zshenv"])
    _link(plan, "zsh", ".zshrc")
    assert stow.pending_links(plan) == ("link zsh",)


def test_stow_ignores_the_files_it_never_links(tmp_path):
    plan = _stow_plan(tmp_path)
    (plan.dotfiles_dir / ".stow-packages").write_text("zsh\n")
    _package(plan.dotfiles_dir, "zsh", [".zshrc", "README.md", "LICENSE", ".gitignore", "notes~"])
    _link(plan, "zsh", ".zshrc")
    assert stow.pending_links(plan) == ()


def test_stow_does_not_count_a_file_the_overlay_overrides(tmp_path):
    plan = _stow_plan(tmp_path, overlay=True)
    (plan.dotfiles_dir / ".stow-packages").write_text("claude\n")
    (plan.overlay_root / ".stow-packages").write_text("claude\n")
    _package(plan.dotfiles_dir, "claude", ["CLAUDE.md", "keep.md"])
    _package(plan.overlay_root, "claude", ["CLAUDE.md"])
    _link(plan, "claude", "keep.md")
    _link(plan, "claude", "CLAUDE.md", plan.overlay_root)
    assert stow.pending_links(plan) == ()


def _ignoring_plan(tmp_path, ignore_text, files):
    plan = _stow_plan(tmp_path)
    (plan.dotfiles_dir / ".stow-packages").write_text("claude\n")
    _package(plan.dotfiles_dir, "claude", [*files, ".stow-local-ignore"])
    (plan.dotfiles_dir / "claude" / ".stow-local-ignore").write_text(ignore_text)
    return plan


def test_stow_local_ignore_patterns_with_a_slash_match_from_the_package_root(tmp_path):
    plan = _ignoring_plan(tmp_path, "# note\n^/\\.claude/settings\\.json\n^/gitconfig-work$\n", [".claude/settings.json", "gitconfig-work", "keep"])
    _link(plan, "claude", "keep")
    assert stow.pending_links(plan) == ()


def test_stow_local_ignore_patterns_cover_everything_below_a_matched_directory(tmp_path):
    plan = _ignoring_plan(tmp_path, "^/\\.claude/skills/synced\n", [".claude/skills/synced/a/b", "keep"])
    _link(plan, "claude", "keep")
    assert stow.pending_links(plan) == ()


def test_stow_local_ignore_patterns_without_a_slash_match_any_path_component(tmp_path):
    plan = _ignoring_plan(tmp_path, "cache\n", ["a/cache/x", "keep"])
    _link(plan, "claude", "keep")
    assert stow.pending_links(plan) == ()


def test_a_local_ignore_file_replaces_the_default_list(tmp_path):
    plan = _ignoring_plan(tmp_path, "nothing-matches\n", ["README.md", "keep"])
    _link(plan, "claude", "keep")
    assert stow.pending_links(plan) == ("link claude",)


def test_a_local_ignore_file_does_not_hide_files_it_does_not_name(tmp_path):
    plan = _ignoring_plan(tmp_path, "^/\\.claude/settings\\.json\n", [".claude/settings.json", "unlinked"])
    assert stow.pending_links(plan) == ("link claude",)


def test_an_invalid_local_ignore_pattern_is_skipped(tmp_path):
    plan = _ignoring_plan(tmp_path, "([unclosed\n", ["keep"])
    _link(plan, "claude", "keep")
    assert stow.pending_links(plan) == ()


def _folded_plan(tmp_path, monkeypatch):
    plan = _stow_plan(tmp_path)
    (plan.dotfiles_dir / ".stow-packages").write_text("gradle\n")
    _package(plan.dotfiles_dir, "gradle", [".gradle/caches/a", ".gradle/caches/b"])
    monkeypatch.setattr(stow, "_package_files", lambda root: (_ for _ in ()).throw(AssertionError("walked the package")))
    return plan


def test_a_folded_package_is_checked_at_the_top_level_without_walking_it(tmp_path, monkeypatch):
    plan = _folded_plan(tmp_path, monkeypatch)
    assert stow.pending_links(plan) == ("link gradle",)


def test_a_folded_package_linked_at_the_top_level_is_not_pending(tmp_path, monkeypatch):
    plan = _folded_plan(tmp_path, monkeypatch)
    (plan.t.home / ".gradle").symlink_to(plan.dotfiles_dir / "gradle" / ".gradle")
    assert stow.pending_links(plan) == ()


def test_a_folded_package_whose_target_is_an_empty_real_directory_is_pending(tmp_path, monkeypatch):
    plan = _folded_plan(tmp_path, monkeypatch)
    (plan.t.home / ".gradle").mkdir()
    assert stow.pending_links(plan) == ("link gradle",)


def test_a_folded_package_whose_real_directory_holds_the_links_is_not_pending(tmp_path, monkeypatch):
    plan = _folded_plan(tmp_path, monkeypatch)
    (plan.t.home / ".gradle").mkdir()
    (plan.t.home / ".gradle" / "caches").symlink_to(plan.dotfiles_dir / "gradle" / ".gradle" / "caches")
    assert stow.pending_links(plan) == ()


def test_a_file_in_a_real_directory_of_a_folded_package_is_checked(tmp_path):
    plan = _stow_plan(tmp_path)
    (plan.dotfiles_dir / ".stow-packages").write_text("gradle\n")
    _package(plan.dotfiles_dir, "gradle", [".gradle/gradle.properties"])
    (plan.t.home / ".gradle").mkdir()
    assert stow.pending_links(plan) == ("link gradle",)


def test_a_folded_package_skips_a_file_the_overlay_overrides(tmp_path):
    plan = _stow_plan(tmp_path, overlay=True)
    (plan.dotfiles_dir / ".stow-packages").write_text("gradle\n")
    (plan.overlay_root / ".stow-packages").write_text("gradle\n")
    _package(plan.dotfiles_dir, "gradle", [".gradle/gradle.properties", ".gradle/keep"])
    _package(plan.overlay_root, "gradle", [".gradle/gradle.properties"])
    (plan.t.home / ".gradle").mkdir()
    _link(plan, "gradle", ".gradle/keep")
    _link(plan, "gradle", ".gradle/gradle.properties", plan.overlay_root)
    assert stow.pending_links(plan) == ()


def test_a_dangling_package_symlink_that_is_linked_is_not_pending(tmp_path):
    plan = _stow_plan(tmp_path)
    (plan.dotfiles_dir / ".stow-packages").write_text("zsh\n")
    (plan.dotfiles_dir / "zsh").mkdir()
    (plan.dotfiles_dir / "zsh" / "dangling").symlink_to(tmp_path / "missing")
    (plan.t.home / "dangling").symlink_to(plan.dotfiles_dir / "zsh" / "dangling")
    assert stow.pending_links(plan) == ()


def test_a_dangling_package_symlink_that_is_not_linked_is_pending(tmp_path):
    plan = _stow_plan(tmp_path)
    (plan.dotfiles_dir / ".stow-packages").write_text("zsh\n")
    (plan.dotfiles_dir / "zsh").mkdir()
    (plan.dotfiles_dir / "zsh" / "dangling").symlink_to(tmp_path / "missing")
    assert stow.pending_links(plan) == ("link zsh",)


def test_ignore_pattern_parsing_is_linear_on_long_whitespace_runs():
    text = "a" + " " * 200000 + "b\n"
    assert stow._strip_comment(text.strip()) == text.strip()


@pytest.mark.parametrize(
    "line,expected",
    [("a # b # c", "a"), ("a #", "a #"), ("a#b", "a#b"), ("a # ", "a #"), ("a #  # x", "a"), ("a \\#b", "a \\#b")],
)
def test_strip_comment_matches_stows_regex(line, expected):
    assert stow._strip_comment(line.strip()) == expected


def test_a_trailing_comment_in_a_local_ignore_line_is_not_part_of_the_pattern(tmp_path):
    plan = _ignoring_plan(tmp_path, "cache # generated files\n", ["a/cache", "keep"])
    _link(plan, "claude", "keep")
    assert stow.pending_links(plan) == ()


def test_the_global_ignore_file_replaces_the_default_list_without_a_local_one(tmp_path):
    plan = _stow_plan(tmp_path)
    (plan.dotfiles_dir / ".stow-packages").write_text("zsh\n")
    _package(plan.dotfiles_dir, "zsh", ["README.md", "skipme", "keep"])
    (plan.t.home / ".stow-global-ignore").write_text("skipme\n")
    _link(plan, "zsh", "keep")
    assert stow.pending_links(plan) == ("link zsh",)
    _link(plan, "zsh", "README.md")
    assert stow.pending_links(plan) == ()


def test_a_local_ignore_pattern_with_a_slash_does_not_match_inside_a_longer_name(tmp_path):
    plan = _ignoring_plan(tmp_path, "foo/bar\n", ["myfoo/bar", "keep"])
    _link(plan, "claude", "keep")
    assert stow.pending_links(plan) == ("link claude",)


def test_a_local_ignore_pattern_with_a_slash_matches_at_a_component_boundary(tmp_path):
    plan = _ignoring_plan(tmp_path, "foo/bar\n", ["x/foo/bar", "keep"])
    _link(plan, "claude", "keep")
    assert stow.pending_links(plan) == ()


def test_stow_reports_an_overlay_package_that_is_not_linked(tmp_path):
    plan = _stow_plan(tmp_path, overlay=True)
    (plan.overlay_root / ".stow-packages").write_text("local\n")
    _package(plan.overlay_root, "local", ["a"])
    assert stow.pending_links(plan) == ("link local (overlay)",)


def test_stow_reports_links_left_by_another_preset(tmp_path):
    plan = _stow_plan(tmp_path, overlay=True, preset="work")
    (plan.overlay_root / ".stow-packages.personal").write_text("only-personal\n")
    _package(plan.overlay_root, "only-personal", ["a"])
    _link(plan, "only-personal", "a", plan.overlay_root)
    assert stow.pending_links(plan) == ("unlink only-personal",)


def test_stow_without_a_stow_packages_file_has_nothing_pending(tmp_path):
    assert stow.pending_links(_stow_plan(tmp_path)) == ()


def test_zsh_cache_is_pending_until_the_fingerprint_is_recorded(tmp_path):
    (tmp_path / ".config/zsh/completions").mkdir(parents=True)
    (tmp_path / ".config/zsh/completions/_x").write_text("#compdef x\n")
    assert zsh_cache.pending(tmp_path)
    store = tmp_path / zsh_cache.FINGERPRINT_FILE
    store.parent.mkdir(parents=True)
    store.write_text(zsh_cache.fingerprint(tmp_path) + "\n")
    assert not zsh_cache.pending(tmp_path)


def test_secrets_env_is_pending_when_missing(tmp_path):
    assert secrets_env.pending(tmp_path) == (f"create {secrets_env.secrets_path(tmp_path)}",)


def test_a_missing_secrets_env_in_a_loose_directory_also_plans_the_directory_restriction(tmp_path):
    path = secrets_env.secrets_path(tmp_path)
    path.parent.mkdir(parents=True)
    path.parent.chmod(0o755)
    assert secrets_env.pending(tmp_path) == (f"create {path}", f"restrict {path.parent} to 700")


def test_secrets_env_is_pending_when_group_or_other_can_read_it(tmp_path):
    path = secrets_env.secrets_path(tmp_path)
    path.parent.mkdir(parents=True, mode=0o700)
    path.write_text("")
    path.chmod(0o644)
    assert secrets_env.pending(tmp_path) == (f"restrict {path} to 0600",)


def test_secrets_env_is_not_pending_when_protected(tmp_path):
    path = secrets_env.secrets_path(tmp_path)
    path.parent.mkdir(parents=True, mode=0o700)
    path.write_text("")
    path.chmod(0o600)
    assert secrets_env.pending(tmp_path) == ()


def test_claude_profile_lists_only_generated_files(tmp_path):
    wrapper = tmp_path / "bin/claude"
    wrapper.parent.mkdir()
    wrapper.write_text(claude_profile.SCRIPT_MARKER)
    (tmp_path / ".zshrc.profile").write_text("hand written")
    assert claude_profile.pending_files(tmp_path) == (wrapper,)


def test_claude_profile_lists_retired_profile_files(tmp_path):
    profile = tmp_path / ".config/dotfiles/claude-profiles/claude_work.json"
    profile.parent.mkdir(parents=True)
    profile.write_text("{}")
    assert claude_profile.pending_files(tmp_path) == (profile,)


def test_user_links_lists_an_installed_tool_that_is_not_linked(tmp_path):
    real = tmp_path / ".local/share/sonarqube-cli/bin/sonar"
    real.parent.mkdir(parents=True)
    real.write_text("")
    t = _t(tmp_path)
    assert user_links.pending(t, {"sonarqube-cli"}) == (f"link {tmp_path / '.local/bin/sonar'}",)
    assert user_links.pending(t, set()) == ()


def test_user_links_is_empty_once_linked(tmp_path):
    real = tmp_path / ".local/share/sonarqube-cli/bin/sonar"
    real.parent.mkdir(parents=True)
    real.write_text("")
    link = tmp_path / ".local/bin/sonar"
    link.parent.mkdir(parents=True)
    link.symlink_to(real)
    assert user_links.pending(_t(tmp_path), {"sonarqube-cli"}) == ()


def test_user_binaries_lists_the_missing_wanted_pins(tmp_path, monkeypatch):
    monkeypatch.setattr(release_installers.platform, "machine", lambda: release_installers.SUPPORTED_ARCH)
    package = release_installers.USER_BINARY_SPECS[0][0]
    t = _t(tmp_path)
    assert release_installers.pending_user_binaries(t, {package}) == [package]
    binary = tmp_path / ".local/bin" / (release_installers.SPEC_DATA[package].binary or package)
    binary.parent.mkdir(parents=True)
    binary.write_text("")
    binary.chmod(0o755)
    assert release_installers.pending_user_binaries(t, {package}) == []


def test_user_binaries_are_never_pending_on_another_architecture(tmp_path, monkeypatch):
    monkeypatch.setattr(release_installers.platform, "machine", lambda: "aarch64")
    package = release_installers.USER_BINARY_SPECS[0][0]
    assert release_installers.pending_user_binaries(_t(tmp_path), {package}) == []


def test_tools_lists_the_wanted_installers_whose_marker_is_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(release_installers.platform, "machine", lambda: release_installers.SUPPORTED_ARCH)
    monkeypatch.setattr("shutil.which", lambda name: None)
    (tmp_path / ".sdkman").mkdir()
    assert tools.pending_tools(_t(tmp_path), {"oh-my-zsh", "sdkman", "nvm"}) == ["oh-my-zsh", "nvm"]


def test_tools_ignores_installers_that_are_not_wanted(tmp_path):
    assert tools.pending_tools(_t(tmp_path), set()) == []


@pytest.mark.parametrize(("value", "pending"), [("['<Control><Shift>u']", True), ("['<Alt>e']", False), ("[]", False)])
def test_ibus_hotkey_is_pending_only_when_ctrl_shift_u_is_bound(tmp_path, monkeypatch, value, pending):
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/gsettings")
    run = lambda argv, **kw: SimpleNamespace(returncode=0, stdout=value + "\n", stderr="")
    assert desktop_defaults.ibus_hotkey_pending(_t(tmp_path, run)) is pending


def test_ibus_hotkey_is_not_pending_without_gsettings(tmp_path, monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: None)
    assert desktop_defaults.ibus_hotkey_pending(_t(tmp_path)) is False


def test_ibus_hotkey_is_not_pending_when_the_schema_is_unreadable(tmp_path, monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/gsettings")
    run = lambda argv, **kw: SimpleNamespace(returncode=1, stdout="", stderr="no schema")
    assert desktop_defaults.ibus_hotkey_pending(_t(tmp_path, run)) is False


def test_the_checks_leave_the_home_untouched(tmp_path):
    before = sorted(os.listdir(tmp_path))
    zsh_cache.pending(tmp_path)
    secrets_env.pending(tmp_path)
    claude_profile.pending_files(tmp_path)
    user_links.pending(_t(tmp_path), {"sonarqube-cli"})
    assert sorted(os.listdir(tmp_path)) == before
