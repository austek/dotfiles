import json

import pytest
from dotfiles_setup import overlay, state
from dotfiles_setup.cli import build_arg_parser, main


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


def test_dry_run_defaults_false():
    parser = build_arg_parser()
    args = parser.parse_args(["install", "--preset", "work"])
    assert args.dry_run is False


def test_dry_run_flag_sets_true():
    parser = build_arg_parser()
    args = parser.parse_args(["install", "--preset", "work", "--dry-run"])
    assert args.dry_run is True


def test_verbosity_defaults_zero():
    parser = build_arg_parser()
    args = parser.parse_args(["install", "--preset", "work"])
    assert args.verbosity == 0


def test_verbose_flag_adds_one():
    parser = build_arg_parser()
    args = parser.parse_args(["install", "--preset", "work", "-v"])
    assert args.verbosity == 1


def test_vv_flag_adds_two():
    parser = build_arg_parser()
    args = parser.parse_args(["install", "--preset", "work", "-vv"])
    assert args.verbosity == 2


def test_vvv_flag_adds_three():
    parser = build_arg_parser()
    args = parser.parse_args(["install", "--preset", "work", "-vvv"])
    assert args.verbosity == 3


def test_verbosity_accumulates_across_distinct_flags():
    parser = build_arg_parser()
    args = parser.parse_args(["install", "--preset", "work", "-v", "-vv"])
    assert args.verbosity == 3


def test_main_returns_zero_for_valid_preset(isolated_dotfiles, capsys):
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
def isolated_dotfiles(tmp_path, monkeypatch, plugin_updates):
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
    monkeypatch.setattr("dotfiles_setup.cli.CLAUDE_HOME", tmp_path / "claude-home")
    monkeypatch.setattr(state, "STATE_DIR", tmp_path / "state")
    monkeypatch.setattr(state, "STATE_FILE", tmp_path / "state" / "state.json")
    monkeypatch.setattr(state, "PACKAGE_DIR", tmp_path / "state" / "packages")
    monkeypatch.setattr("dotfiles_setup.cli.state.STATE_FILE", tmp_path / "state" / "state.json")
    monkeypatch.setattr("dotfiles_setup.cli.state.PACKAGE_DIR", tmp_path / "state" / "packages")
    monkeypatch.setattr(overlay, "find_overlay_root", lambda: None)
    monkeypatch.setattr("dotfiles_setup.cli.update.pull_if_behind", lambda *a, **kw: False)
    monkeypatch.setattr("dotfiles_setup.cli.identity.ensure_git_identity", lambda **kw: tmp_path / "gitconfig.local")

    def fake_run(argv, **kwargs):
        class _Result:
            returncode = 0
            stdout = "installed"
            stderr = ""
        return _Result()

    monkeypatch.setattr("dotfiles_setup.cli.subprocess.run", fake_run)
    return dotfiles_dir, tmp_path


def test_install_creates_package_file_on_first_run(isolated_dotfiles, capsys):
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
    package_file.write_text(package_file.read_text() + "ripgrep\n")  # user hand-edit
    main(["install", "--preset", "homelab"])
    assert "ripgrep" in package_file.read_text()


def test_install_reports_backend_failure(isolated_dotfiles, monkeypatch):
    def failing_run(argv, **kwargs):
        class _Result:
            returncode = 1
            stdout = "apt-get exploded"
            stderr = ""
        return _Result()

    monkeypatch.setattr("dotfiles_setup.cli.subprocess.run", failing_run)
    assert main(["install", "--preset", "homelab"]) == 1


def test_install_reports_backend_failure_with_no_captured_output(isolated_dotfiles, capsys, monkeypatch):
    """The real run() no longer captures setup.sh's output (it streams live
    instead), so a real failure has nothing in result.stdout to print back —
    cli.py falls back to a message naming the exit code instead of a blank line."""
    def failing_run(argv, **kwargs):
        class _Result:
            returncode = 3
            stdout = None
            stderr = None
        return _Result()

    monkeypatch.setattr("dotfiles_setup.cli.subprocess.run", failing_run)
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


def test_dry_run_skips_state_persistence(isolated_dotfiles):
    main(["install", "--preset", "homelab", "--dry-run"])
    assert state.load_state() is None


def test_install_does_not_persist_state_on_failure(isolated_dotfiles, monkeypatch):
    def failing_run(argv, **kwargs):
        class _Result:
            returncode = 1
            stdout = "apt-get exploded"
            stderr = ""
        return _Result()

    monkeypatch.setattr("dotfiles_setup.cli.subprocess.run", failing_run)
    main(["install", "--preset", "homelab"])
    assert state.load_state() is None


def test_install_forwards_verbosity_to_backend(isolated_dotfiles, monkeypatch):
    """The exact bug the user hit: -v/-vv/-vvv changed dotfiles-setup's own
    logging but never reached setup.sh, so its VERBOSITY stayed 0 no matter
    what was typed and output looked identical at every level."""
    calls = []

    def recording_run(argv, **kwargs):
        calls.append(argv)

        class _Result:
            returncode = 0
            stdout = "installed"
            stderr = ""
        return _Result()

    monkeypatch.setattr("dotfiles_setup.cli.subprocess.run", recording_run)

    assert main(["install", "--preset", "homelab", "-vv"]) == 0
    assert calls[0][calls[0].index("--verbosity") + 1] == "2"


def test_install_passes_private_root_to_backend_when_overlay_present(isolated_dotfiles, monkeypatch, tmp_path):
    calls = []

    def recording_run(argv, **kwargs):
        calls.append(argv)

        class _Result:
            returncode = 0
            stdout = "installed"
            stderr = ""
        return _Result()

    private_root = tmp_path / "dotfiles-private"
    monkeypatch.setattr(overlay, "find_overlay_root", lambda: private_root)
    monkeypatch.setattr("dotfiles_setup.cli.subprocess.run", recording_run)

    assert main(["install", "--preset", "homelab"]) == 0
    assert calls[0][-2:] == ["--private-root", str(private_root)]


def test_install_omits_private_root_when_no_overlay(isolated_dotfiles, monkeypatch):
    calls = []

    def recording_run(argv, **kwargs):
        calls.append(argv)

        class _Result:
            returncode = 0
            stdout = "installed"
            stderr = ""
        return _Result()

    monkeypatch.setattr("dotfiles_setup.cli.subprocess.run", recording_run)

    assert main(["install", "--preset", "homelab"]) == 0
    assert "--private-root" not in calls[0]


def test_install_raises_helpful_error_for_unknown_preset(isolated_dotfiles, capsys):
    assert main(["install", "--preset", "nonexistent"]) == 1
    assert "nonexistent" in capsys.readouterr().err


def test_install_checks_for_dotfiles_updates_first(isolated_dotfiles, monkeypatch):
    seen = []
    monkeypatch.setattr("dotfiles_setup.cli.update.pull_if_behind", lambda repo, logger: seen.append(repo) or False)
    main(["install", "--preset", "homelab"])
    assert seen == [isolated_dotfiles[0]]


def test_install_pulls_private_overlay_after_dotfiles(isolated_dotfiles, monkeypatch, tmp_path):
    private = tmp_path / "private"
    private.mkdir()
    seen = []
    monkeypatch.setattr("dotfiles_setup.cli.overlay.find_overlay_root", lambda: private)
    monkeypatch.setattr("dotfiles_setup.cli.update.pull_overlay_if_git", lambda root, logger: seen.append(root) or False)
    main(["install", "--preset", "homelab"])
    assert seen == [private]


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
    before = settings.stat().st_mtime_ns
    assert main(["install", "--preset", "homelab"]) == 0
    assert settings.stat().st_mtime_ns == before
    assert not list(settings.parent.glob("settings.json.bak-*"))


def test_install_updates_claude_plugins_after_a_successful_install(isolated_dotfiles, plugin_updates):
    assert main(["install", "--preset", "homelab"]) == 0
    assert len(plugin_updates) == 1


def test_install_skips_claude_plugin_update_when_the_backend_fails(isolated_dotfiles, plugin_updates, monkeypatch):
    def failing_run(argv, **kwargs):
        class _Result:
            returncode = 1
            stdout = "boom"
            stderr = ""
        return _Result()

    monkeypatch.setattr("dotfiles_setup.cli.subprocess.run", failing_run)
    main(["install", "--preset", "homelab"])
    assert plugin_updates == []


def test_settings_replacement_leaves_a_preexisting_shared_tmp_file_alone(tmp_path):
    from datetime import UTC, datetime

    from dotfiles_setup.cli import _replace_settings_target

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
    calls = []

    def recording_run(argv, **kwargs):
        calls.append(argv)

        class _Result:
            returncode = 0
            stdout = ""
            stderr = ""
        return _Result()

    default_root = tmp_path / "dotfiles-private"
    monkeypatch.setattr("dotfiles_setup.cli.overlay.DEFAULT_OVERLAY_ROOT", default_root)
    monkeypatch.setattr("dotfiles_setup.cli.subprocess.run", recording_run)

    assert main(["private", "clone", "--repo", "git@github.com:you/dotfiles-private.git"]) == 0
    assert calls == [["git", "clone", "git@github.com:you/dotfiles-private.git", str(default_root)]]


def test_main_private_clone_honors_dest_override(tmp_path, monkeypatch):
    calls = []

    def recording_run(argv, **kwargs):
        calls.append(argv)

        class _Result:
            returncode = 0
            stdout = ""
            stderr = ""
        return _Result()

    dest = tmp_path / "custom-dest"
    monkeypatch.setattr("dotfiles_setup.cli.subprocess.run", recording_run)

    assert main(["private", "clone", "--repo", "git@example.com/x.git", "--dest", str(dest)]) == 0
    assert calls[0][-1] == str(dest)


def test_main_private_clone_dry_run_does_not_clone(tmp_path, monkeypatch, capsys):
    def unexpected_run(argv, **kwargs):
        raise AssertionError("git clone should not run in dry-run mode")

    monkeypatch.setattr("dotfiles_setup.cli.subprocess.run", unexpected_run)

    dest = tmp_path / "dotfiles-private"
    assert main(["private", "clone", "--repo", "git@example.com/x.git", "--dest", str(dest), "--dry-run"]) == 0
    assert "DRY-RUN" in capsys.readouterr().out
    assert not dest.exists()


def test_main_private_clone_returns_nonzero_on_git_failure(tmp_path, monkeypatch, capsys):
    def failing_run(argv, **kwargs):
        class _Result:
            returncode = 128
            stdout = ""
            stderr = "fatal: repository not found"
        return _Result()

    monkeypatch.setattr("dotfiles_setup.cli.subprocess.run", failing_run)

    dest = tmp_path / "dotfiles-private"
    assert main(["private", "clone", "--repo", "git@example.com/x.git", "--dest", str(dest)]) == 128
    assert "not found" in capsys.readouterr().err


def test_install_force_flag_reaches_setup_sh(isolated_dotfiles, monkeypatch):
    calls = []

    def recording_run(argv, **kwargs):
        calls.append(argv)

        class _Result:
            returncode = 0
            stdout = ""
            stderr = ""
        return _Result()

    monkeypatch.setattr("dotfiles_setup.cli.subprocess.run", recording_run)

    assert main(["install", "--preset", "homelab", "--force"]) == 0
    assert "--force-stow" in calls[0]
