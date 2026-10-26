import json
import os
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from dotfiles_setup import overlay, state
from dotfiles_setup.backends.apt import AptBackend
from dotfiles_setup.cli import (
    Env,
    _replace_settings_target,
    build_arg_parser,
    combine_package_names,
    main,
)


def test_combine_package_names_resolves_overrides_and_merges_overlay(tmp_path):
    backend = AptBackend(dotfiles_dir=tmp_path, backend_overrides={"bat": "batcat"})
    assert combine_package_names(backend, ("bat", "git"), ("zsh", "git")) == ("batcat", "git", "zsh")


def test_preset_is_optional_at_parse_time():
    args = build_arg_parser().parse_args(["install"])
    assert args.preset is None


def test_preset_accepts_any_value_at_parse_time():
    """Preset existence is validated by presets.load_preset(), not argparse —
    an unknown name here is a runtime FileNotFoundError, not a parse error."""
    parser = build_arg_parser()
    args = parser.parse_args(["install", "--preset", "bogus"])
    assert args.preset == "bogus"


@pytest.mark.parametrize("preset", ["work", "personal", "homelab"])
def test_preset_accepts_valid_values(preset):
    parser = build_arg_parser()
    args = parser.parse_args(["install", "--preset", preset])
    assert args.preset == preset


@pytest.mark.parametrize(("flags", "expected"), [([], False), (["--dry-run"], True)])
def test_dry_run_flag(flags, expected):
    args = build_arg_parser().parse_args(["install", "--preset", "work", *flags])
    assert args.dry_run is expected


@pytest.mark.parametrize(
    ("flags", "expected"),
    [([], 0), (["-v"], 1), (["-vv"], 2), (["-vvv"], 3)],
)
def test_verbosity_flag(flags, expected):
    args = build_arg_parser().parse_args(["install", "--preset", "work", *flags])
    assert args.verbosity == expected


def test_verbosity_accumulates_across_distinct_flags():
    parser = build_arg_parser()
    args = parser.parse_args(["install", "--preset", "work", "-v", "-vv"])
    assert args.verbosity == 3


def test_main_returns_zero_for_valid_preset(isolated_dotfiles):
    assert main(["install", "--preset", "homelab"]) == 0


def test_main_prints_dry_run_banner_when_requested(isolated_dotfiles, capsys):
    main(["install", "--preset", "homelab", "--dry-run"])
    assert "DRY-RUN MODE" in capsys.readouterr().out


def test_main_does_not_print_dry_run_banner_otherwise(isolated_dotfiles, capsys):
    main(["install", "--preset", "homelab"])
    assert "DRY-RUN MODE" not in capsys.readouterr().out


def test_main_without_command_prints_help_and_returns_1(capsys):
    assert main([]) == 1
    out = capsys.readouterr().out
    assert "usage:" in out
    assert "install" in out


def test_top_level_help_lists_install_subcommand_and_examples(capsys):
    parser = build_arg_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["-h"])
    out = capsys.readouterr().out
    assert "install" in out
    assert "Examples:" in out
    assert "dotfiles-setup install --preset work" in out


@pytest.fixture
def plugin_updates(monkeypatch):
    calls = []
    monkeypatch.setattr("dotfiles_setup.cli.claude_plugins.update_claude_plugins", lambda logger, settings: calls.append(logger))
    return calls


@pytest.fixture
def foothold_installs(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "dotfiles_setup.cli.foothold.install_foothold",
        lambda logger, preset_name, profile_path: calls.append((preset_name, profile_path)) or True,
    )
    return calls


def stub_subprocess(monkeypatch, returncode=0, stdout="installed", stderr="", calls=None):
    calls = [] if calls is None else calls

    def run(argv, **kwargs):
        calls.append(argv)
        return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)

    monkeypatch.setattr("dotfiles_setup.cli.subprocess.run", run)
    return calls


@pytest.fixture
def foothold_retirements(monkeypatch):
    calls = []
    monkeypatch.setattr("dotfiles_setup.cli.foothold.retire_foothold", lambda logger, preset_name: calls.append(preset_name))
    return calls


@pytest.fixture
def isolated_dotfiles(tmp_path, monkeypatch, plugin_updates, foothold_installs, foothold_retirements):
    """A minimal fake dotfiles_dir with one preset + its package files, plus
    state/overlay redirected into tmp_path so tests never touch the real
    machine's ~/.config/dotfiles or ~/.dotfiles-private."""
    dotfiles_dir = tmp_path / "dotfiles"
    (dotfiles_dir / "presets").mkdir(parents=True)
    (dotfiles_dir / "packages").mkdir(parents=True)
    (dotfiles_dir / "claude-profiles").mkdir(parents=True)
    (dotfiles_dir / "presets" / "homelab.json").write_text(json.dumps({
        "description": "test",
        "package_files": ["apt_common.txt"],
        "backend_overrides": {},
        "claude_settings": "claude_homelab.json",
    }))
    (dotfiles_dir / "packages" / "apt_common.txt").write_text("zsh\ncurl\n")
    (dotfiles_dir / "claude-profiles" / "claude_homelab.json").write_text(json.dumps({"enabledPlugins": {}}))

    (dotfiles_dir / "claude" / ".claude").mkdir(parents=True)
    (dotfiles_dir / "claude" / ".claude" / "settings.json").write_text(json.dumps({"model": "base"}))

    monkeypatch.setattr("dotfiles_setup.cli._dotfiles_dir", lambda: dotfiles_dir)
    monkeypatch.setattr("dotfiles_setup.cli._claude_home", lambda: tmp_path / "claude-home")
    monkeypatch.setattr(state, "state_dir", lambda: tmp_path / "state")
    monkeypatch.setattr(overlay, "find_overlay_root", lambda: None)
    monkeypatch.setattr("dotfiles_setup.cli.update.pull_if_behind", lambda *a, **kw: False)
    monkeypatch.setattr("dotfiles_setup.cli.identity.ensure_git_identity", lambda **kw: tmp_path / "gitconfig.local")
    stub_subprocess(monkeypatch)
    return dotfiles_dir, tmp_path


def test_install_creates_package_file_on_first_run(isolated_dotfiles):
    _dotfiles_dir, tmp_path = isolated_dotfiles
    assert main(["install", "--preset", "homelab"]) == 0
    package_file = tmp_path / "state" / "packages" / "homelab.txt"
    assert package_file.is_file()
    assert set(package_file.read_text().split()) == {"zsh", "curl"}


def test_install_persists_state(isolated_dotfiles):
    main(["install", "--preset", "homelab"])
    saved = state.load_state()
    assert saved.preset_name == "homelab"
    assert saved.backend == "apt"


def test_install_is_idempotent_on_rerun(isolated_dotfiles):
    _dotfiles_dir, tmp_path = isolated_dotfiles
    main(["install", "--preset", "homelab"])
    package_file = tmp_path / "state" / "packages" / "homelab.txt"
    package_file.write_text(package_file.read_text() + "ripgrep\n")
    main(["install", "--preset", "homelab"])
    assert "ripgrep" in package_file.read_text()


def test_install_reports_backend_failure(isolated_dotfiles, monkeypatch):
    stub_subprocess(monkeypatch, returncode=1, stdout="apt-get exploded")
    assert main(["install", "--preset", "homelab"]) == 1


def test_install_reports_backend_failure_with_no_captured_output(isolated_dotfiles, capsys, monkeypatch):
    """Names the exit code when the streamed backend run left no output to print."""
    stub_subprocess(monkeypatch, returncode=3, stdout=None, stderr=None)
    assert main(["install", "--preset", "homelab"]) == 3
    assert "exited with code 3" in capsys.readouterr().err


def test_dry_run_skips_git_identity(isolated_dotfiles, monkeypatch):
    calls = []
    monkeypatch.setattr(
        "dotfiles_setup.cli.identity.ensure_git_identity",
        lambda **kw: calls.append(kw) or None,
    )
    main(["install", "--preset", "homelab", "--dry-run"])
    assert calls == []


def test_dry_run_skips_claude_profile_write(isolated_dotfiles):
    _dotfiles_dir, tmp_path = isolated_dotfiles
    main(["install", "--preset", "homelab", "--dry-run"])
    assert not (tmp_path / "state" / "claude-profiles" / "claude_homelab.json").exists()


def test_dry_run_still_forks_the_package_file_setup_sh_reads(isolated_dotfiles):
    main(["install", "--preset", "homelab", "--dry-run"])
    assert (state.package_dir() / "homelab.txt").exists()


def test_dry_run_skips_state_persistence(isolated_dotfiles):
    main(["install", "--preset", "homelab", "--dry-run"])
    assert state.load_state() is None


def test_install_does_not_persist_state_on_failure(isolated_dotfiles, monkeypatch):
    stub_subprocess(monkeypatch, returncode=1, stdout="apt-get exploded")
    main(["install", "--preset", "homelab"])
    assert state.load_state() is None


def test_install_forwards_verbosity_to_backend(isolated_dotfiles, monkeypatch):
    calls = stub_subprocess(monkeypatch)
    assert main(["install", "--preset", "homelab", "-vv"]) == 0
    assert calls[0][calls[0].index("--verbosity") + 1] == "2"


def test_install_passes_private_root_to_backend_when_overlay_present(isolated_dotfiles, monkeypatch, tmp_path):
    private_root = tmp_path / "dotfiles-private"
    monkeypatch.setattr(overlay, "find_overlay_root", lambda: private_root)
    calls = stub_subprocess(monkeypatch)
    assert main(["install", "--preset", "homelab"]) == 0
    setup_calls = [call for call in calls if "--only" in call]
    assert setup_calls
    assert all(call[call.index("--private-root") + 1] == str(private_root) for call in setup_calls)


def test_install_runs_setup_sh_in_segments_around_the_tool_installers(isolated_dotfiles, monkeypatch):
    calls = stub_subprocess(monkeypatch)
    assert main(["install", "--preset", "homelab"]) == 0
    only = [call[call.index("--only") + 1].split(",") for call in calls if "--only" in call]
    assert [steps[0] for steps in only] == ["install_core_deps", "install_packages", "enable_gpaste_extension"]


def test_install_omits_private_root_when_no_overlay(isolated_dotfiles, monkeypatch):
    calls = stub_subprocess(monkeypatch)
    assert main(["install", "--preset", "homelab"]) == 0
    assert "--private-root" not in calls[0]


def test_install_raises_helpful_error_for_unknown_preset(isolated_dotfiles, capsys):
    assert main(["install", "--preset", "nonexistent"]) == 1
    assert "nonexistent" in capsys.readouterr().err


def test_install_checks_for_dotfiles_updates_before_the_backend_runs(isolated_dotfiles, monkeypatch):
    order = []
    monkeypatch.setattr("dotfiles_setup.cli.update.pull_if_behind", lambda repo, logger: order.append(repo) or False)
    stub_subprocess(monkeypatch, calls=order)
    main(["install", "--preset", "homelab"])
    assert order[0] == isolated_dotfiles[0]
    assert isinstance(order[1], list)


def test_install_pulls_private_overlay_after_dotfiles(isolated_dotfiles, monkeypatch, tmp_path):
    private = tmp_path / "private"
    private.mkdir()
    order = []
    monkeypatch.setattr("dotfiles_setup.cli.overlay.find_overlay_root", lambda: private)
    monkeypatch.setattr("dotfiles_setup.cli.update.pull_if_behind", lambda repo, logger: order.append("dotfiles") or False)
    monkeypatch.setattr("dotfiles_setup.cli.update.pull_overlay_if_git", lambda root, logger: order.append(root) or False)
    main(["install", "--preset", "homelab"])
    assert order == ["dotfiles", private]


def test_install_generates_claude_settings_from_base_and_overlay(isolated_dotfiles, monkeypatch, tmp_path):
    private_root = tmp_path / "private"
    (private_root / "claude-settings").mkdir(parents=True)
    (private_root / "claude-settings" / "settings.json").write_text(json.dumps({"extra": True}))
    monkeypatch.setattr(overlay, "find_overlay_root", lambda: private_root)
    assert main(["install", "--preset", "homelab"]) == 0
    generated = json.loads((tmp_path / "claude-home" / "settings.json").read_text())
    assert generated == {"model": "base", "extra": True}


def test_install_backs_up_a_differing_settings_file(isolated_dotfiles, tmp_path):
    claude_home = tmp_path / "claude-home"
    claude_home.mkdir()
    (claude_home / "settings.json").write_text('{"hand": "edited"}')
    assert main(["install", "--preset", "homelab"]) == 0
    (backup,) = claude_home.glob("settings.json.bak-*")
    assert json.loads(backup.read_text()) == {"hand": "edited"}


def test_install_replaces_settings_symlink_without_writing_through(isolated_dotfiles, tmp_path):
    claude_home = tmp_path / "claude-home"
    claude_home.mkdir()
    repo_copy = tmp_path / "repo-settings.json"
    repo_copy.write_text('{"tracked": true}')
    (claude_home / "settings.json").symlink_to(repo_copy)
    assert main(["install", "--preset", "homelab"]) == 0
    assert not (claude_home / "settings.json").is_symlink()
    assert repo_copy.read_text() == '{"tracked": true}'


def test_dry_run_skips_claude_settings_write(isolated_dotfiles, tmp_path):
    assert main(["install", "--preset", "homelab", "--dry-run"]) == 0
    assert not (tmp_path / "claude-home" / "settings.json").exists()


def test_install_keeps_existing_settings_when_staging_fails(isolated_dotfiles, tmp_path, monkeypatch):
    claude_home = tmp_path / "claude-home"
    claude_home.mkdir()
    (claude_home / "settings.json").write_text('{"hand": "edited"}')

    def failing_fdopen(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr("dotfiles_setup.cli.os.fdopen", failing_fdopen)
    with pytest.raises(OSError):
        main(["install", "--preset", "homelab"])
    assert (claude_home / "settings.json").read_text() == '{"hand": "edited"}'
    assert not list(claude_home.glob("settings.json.bak-*"))
    assert not list(claude_home.glob("settings.json.*.tmp"))


def test_install_leaves_identical_settings_untouched(isolated_dotfiles, tmp_path):
    assert main(["install", "--preset", "homelab"]) == 0
    settings = tmp_path / "claude-home" / "settings.json"
    os.utime(settings, ns=(0, 0))
    assert main(["install", "--preset", "homelab"]) == 0
    assert settings.stat().st_mtime_ns == 0
    assert not list(settings.parent.glob("settings.json.bak-*"))


def _install_then_edit_settings(tmp_path):
    assert main(["install", "--preset", "homelab"]) == 0
    settings = tmp_path / "claude-home" / "settings.json"
    settings.write_text(json.dumps({**json.loads(settings.read_text()), "hand": "edited"}, indent=2) + "\n")
    return settings


def test_install_records_the_generated_settings_as_the_drift_baseline(isolated_dotfiles, tmp_path):
    assert main(["install", "--preset", "homelab"]) == 0
    baseline = tmp_path / "state" / "settings.last-generated.json"
    assert baseline.read_text() == (tmp_path / "claude-home" / "settings.json").read_text()


def test_install_stops_when_settings_were_edited_since_the_last_install(
    isolated_dotfiles, plugin_updates, foothold_installs, tmp_path, capsys,
):
    settings = _install_then_edit_settings(tmp_path)
    edited = settings.read_text()
    assert main(["install", "--preset", "homelab"]) == 3
    assert settings.read_text() == edited
    assert not list(settings.parent.glob("settings.json.bak-*"))
    assert len(plugin_updates) == 1
    assert len(foothold_installs) == 1
    assert '+  "hand": "edited"' in capsys.readouterr().out


def test_install_accepts_a_base_change_when_settings_were_not_edited(isolated_dotfiles, tmp_path):
    dotfiles_dir, _ = isolated_dotfiles
    assert main(["install", "--preset", "homelab"]) == 0
    (dotfiles_dir / "claude" / ".claude" / "settings.json").write_text(json.dumps({"model": "changed"}))
    assert main(["install", "--preset", "homelab"]) == 0
    settings = tmp_path / "claude-home" / "settings.json"
    assert json.loads(settings.read_text()) == {"model": "changed"}


def test_accept_drift_overwrites_edited_settings_and_keeps_a_backup(isolated_dotfiles, tmp_path):
    settings = _install_then_edit_settings(tmp_path)
    edited = settings.read_text()
    assert main(["install", "--preset", "homelab", "--accept-drift"]) == 0
    (backup,) = settings.parent.glob("settings.json.bak-*")
    assert backup.read_text() == edited
    assert json.loads(settings.read_text()) == {"model": "base"}


def test_dry_run_reports_settings_drift_and_continues(isolated_dotfiles, tmp_path, capsys):
    settings = _install_then_edit_settings(tmp_path)
    edited = settings.read_text()
    capsys.readouterr()
    assert main(["install", "--preset", "homelab", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "edited since the last install" in out
    assert '+  "hand": "edited"' in out
    assert settings.read_text() == edited


def test_install_updates_claude_plugins_after_a_successful_install(isolated_dotfiles, plugin_updates):
    assert main(["install", "--preset", "homelab"]) == 0
    assert len(plugin_updates) == 1


def test_install_sets_up_the_foothold_for_the_preset_profile(isolated_dotfiles, foothold_installs):
    assert main(["install", "--preset", "homelab"]) == 0
    assert [(name, path.name) for name, path in foothold_installs] == [("homelab", "claude_homelab.json")]


def _add_preset(dotfiles_dir, name):
    (dotfiles_dir / "presets" / f"{name}.json").write_text(json.dumps({
        "description": "test",
        "package_files": ["apt_common.txt"],
        "backend_overrides": {},
        "claude_settings": f"claude_{name}.json",
    }))
    (dotfiles_dir / "claude-profiles" / f"claude_{name}.json").write_text(json.dumps({"enabledPlugins": {}}))


def test_install_retires_the_previous_presets_foothold_when_the_preset_changes(isolated_dotfiles, foothold_retirements):
    dotfiles_dir, _ = isolated_dotfiles
    _add_preset(dotfiles_dir, "personal")
    assert main(["install", "--preset", "homelab"]) == 0
    assert foothold_retirements == []
    assert main(["install", "--preset", "personal"]) == 0
    assert foothold_retirements == ["homelab"]


def test_install_keeps_the_previous_foothold_when_the_replacement_fails(isolated_dotfiles, foothold_retirements, monkeypatch):
    dotfiles_dir, _ = isolated_dotfiles
    _add_preset(dotfiles_dir, "personal")
    assert main(["install", "--preset", "homelab"]) == 0
    monkeypatch.setattr("dotfiles_setup.cli.foothold.install_foothold", lambda logger, preset_name, profile_path: False)
    assert main(["install", "--preset", "personal"]) == 0
    assert foothold_retirements == []


def test_install_keeps_the_foothold_when_the_preset_is_unchanged(isolated_dotfiles, foothold_retirements):
    assert main(["install", "--preset", "homelab"]) == 0
    assert main(["install", "--preset", "homelab"]) == 0
    assert foothold_retirements == []


def test_install_skips_the_foothold_when_the_backend_fails(isolated_dotfiles, foothold_installs, monkeypatch):
    stub_subprocess(monkeypatch, returncode=1, stdout="boom")
    main(["install", "--preset", "homelab"])
    assert foothold_installs == []


def test_install_skips_claude_plugin_update_when_the_backend_fails(isolated_dotfiles, plugin_updates, monkeypatch):
    stub_subprocess(monkeypatch, returncode=1, stdout="boom")
    main(["install", "--preset", "homelab"])
    assert plugin_updates == []


def test_settings_replacement_leaves_a_preexisting_shared_tmp_file_alone(tmp_path):
    target = tmp_path / "settings.json"
    target.write_text("old")
    other_install = tmp_path / "settings.json.tmp"
    other_install.write_text("in flight")
    _replace_settings_target(target, "new", datetime.now(UTC))
    assert target.read_text() == "new"
    assert other_install.read_text() == "in flight"
    assert sorted(p.name for p in tmp_path.glob("settings.json.*.tmp")) == []


def test_install_without_preset_or_saved_state_fails(isolated_dotfiles, capsys):
    assert main(["install"]) == 2
    assert "pass --preset" in capsys.readouterr().err


def test_install_without_preset_fails_before_touching_the_checkout(isolated_dotfiles, monkeypatch):
    calls = []
    monkeypatch.setattr("dotfiles_setup.cli._prepare_checkout", lambda *a: calls.append(a))
    assert main(["install"]) == 2
    assert calls == []


def test_install_without_preset_reuses_the_saved_one(isolated_dotfiles):
    main(["install", "--preset", "homelab"])
    assert main(["install"]) == 0
    assert state.load_state().preset_name == "homelab"


def test_install_preset_overrides_the_saved_one(isolated_dotfiles):
    dotfiles_dir, _tmp = isolated_dotfiles
    (dotfiles_dir / "presets" / "other.json").write_text(json.dumps({
        "description": "test", "package_files": ["apt_common.txt"], "backend_overrides": {},
    }))
    main(["install", "--preset", "homelab"])
    assert main(["install", "--preset", "other"]) == 0
    assert state.load_state().preset_name == "other"


def test_install_without_preset_reports_an_unknown_saved_preset(isolated_dotfiles):
    dotfiles_dir, _tmp = isolated_dotfiles
    main(["install", "--preset", "homelab"])
    (dotfiles_dir / "presets" / "homelab.json").unlink()
    assert main(["install"]) == 1


def test_install_passes_overlay_root_to_git_identity(isolated_dotfiles, monkeypatch, tmp_path):
    """The overlay must be known before ensure_git_identity runs so a private
    overlay's git/gitconfig.local can suppress the interactive prompt."""
    calls = []
    monkeypatch.setattr(
        "dotfiles_setup.cli.identity.ensure_git_identity",
        lambda **kw: calls.append(kw) or tmp_path / "gitconfig.local",
    )
    private_root = tmp_path / "dotfiles-private"
    monkeypatch.setattr(overlay, "find_overlay_root", lambda: private_root)

    assert main(["install", "--preset", "homelab"]) == 0
    assert calls[0]["overlay_root"] == private_root


def test_private_clone_requires_subcommand():
    parser = build_arg_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["private"])


def test_private_clone_requires_repo():
    parser = build_arg_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["private", "clone"])


def test_private_clone_dest_defaults_to_none():
    parser = build_arg_parser()
    args = parser.parse_args(["private", "clone", "--repo", "git@github.com:you/dotfiles-private.git"])
    assert args.dest is None


def test_main_private_clone_clones_to_default_dest(tmp_path, monkeypatch):
    default_root = tmp_path / "dotfiles-private"
    monkeypatch.setattr("dotfiles_setup.cli.overlay.DEFAULT_OVERLAY_ROOT", default_root)
    calls = stub_subprocess(monkeypatch, stdout="")
    assert main(["private", "clone", "--repo", "git@github.com:you/dotfiles-private.git"]) == 0
    assert calls == [["git", "clone", "git@github.com:you/dotfiles-private.git", str(default_root)]]


def test_main_private_clone_honors_dest_override(tmp_path):
    dest = tmp_path / "custom-dest"
    calls = []

    def run(argv, **kwargs):
        calls.append(argv)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    argv = ["private", "clone", "--repo", "git@example.com/x.git", "--dest", str(dest)]
    assert main(argv, Env(run=run)) == 0
    assert calls[0][-1] == str(dest)


def test_install_uses_injected_clock_and_paths(isolated_dotfiles, tmp_path):
    dotfiles_dir, _ = isolated_dotfiles
    clock_value = datetime(2030, 1, 2, 3, 4, 5, tzinfo=UTC)
    env = Env(
        clock=lambda: clock_value, claude_home=tmp_path / "injected-claude",
        state_dir=tmp_path / "injected-state", dotfiles_dir=dotfiles_dir,
    )
    assert main(["install", "--preset", "homelab"], env) == 0
    saved = state.load_state(tmp_path / "injected-state" / "state.json")
    assert saved.created_at == clock_value.isoformat()
    assert (tmp_path / "injected-claude" / "settings.json").is_file()
    assert (tmp_path / "injected-state" / "packages" / "homelab.txt").is_file()


def test_install_builds_backend_through_injected_factory(isolated_dotfiles):
    dotfiles_dir, _ = isolated_dotfiles
    seen = []

    def factory(directory, overrides):
        seen.append((directory, overrides))
        return AptBackend(dotfiles_dir=directory, backend_overrides=overrides)

    assert main(["install", "--preset", "homelab"], Env(dotfiles_dir=dotfiles_dir, backend_factory=factory)) == 0
    assert seen == [(dotfiles_dir, {})]


def test_env_now_iso_uses_clock():
    env = Env(clock=lambda: datetime(2030, 1, 2, tzinfo=UTC))
    assert env.now_iso() == "2030-01-02T00:00:00+00:00"


def test_each_subcommand_parser_is_built_by_its_own_function():
    parser = build_arg_parser()
    assert parser.parse_args(["install", "-vv", "--force"]).verbosity == 2
    assert parser.parse_args(["private", "clone", "--repo", "x"]).private_command == "clone"


def test_main_private_clone_dry_run_does_not_clone(tmp_path, monkeypatch, capsys):
    def unexpected_run(argv, **kwargs):
        raise AssertionError("git clone should not run in dry-run mode")

    monkeypatch.setattr("dotfiles_setup.cli.subprocess.run", unexpected_run)

    dest = tmp_path / "dotfiles-private"
    assert main(["private", "clone", "--repo", "git@example.com/x.git", "--dest", str(dest), "--dry-run"]) == 0
    assert "DRY-RUN" in capsys.readouterr().out
    assert not dest.exists()


def test_main_private_clone_returns_nonzero_on_git_failure(tmp_path, monkeypatch, capsys):
    stub_subprocess(monkeypatch, returncode=128, stdout="", stderr="fatal: repository not found")
    dest = tmp_path / "dotfiles-private"
    assert main(["private", "clone", "--repo", "git@example.com/x.git", "--dest", str(dest)]) == 128
    assert "not found" in capsys.readouterr().err


def test_install_force_flag_reaches_setup_sh(isolated_dotfiles, monkeypatch):
    calls = stub_subprocess(monkeypatch)
    assert main(["install", "--preset", "homelab", "--force"]) == 0
    assert "--force-stow" in calls[0]


def test_dry_run_install_writes_nothing_to_disk(isolated_dotfiles):
    _, tmp_path = isolated_dotfiles
    assert main(["install", "--preset", "homelab", "--dry-run"]) == 0
    assert not list((tmp_path / "claude-home").rglob("*"))
    assert not (tmp_path / "state" / "state.json").exists()
    assert not (tmp_path / "state" / "claude-profiles").exists()


def test_switching_presets_forks_packages_and_regenerates_state(isolated_dotfiles, foothold_retirements):
    dotfiles_dir, tmp_path = isolated_dotfiles
    _add_preset(dotfiles_dir, "personal")
    assert main(["install", "--preset", "homelab"]) == 0
    assert main(["install", "--preset", "personal"]) == 0
    assert (tmp_path / "state" / "packages" / "homelab.txt").is_file()
    assert (tmp_path / "state" / "packages" / "personal.txt").is_file()
    assert state.load_state().preset_name == "personal"
    assert foothold_retirements == ["homelab"]
