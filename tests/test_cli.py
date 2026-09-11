import json

import pytest
from dotfiles_setup import overlay, state
from dotfiles_setup.cli import build_arg_parser, main


def test_preset_is_required():
    parser = build_arg_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["install"])


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
def isolated_dotfiles(tmp_path, monkeypatch):
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

    monkeypatch.setattr("dotfiles_setup.cli._dotfiles_dir", lambda: dotfiles_dir)
    monkeypatch.setattr(state, "STATE_DIR", tmp_path / "state")
    monkeypatch.setattr(state, "STATE_FILE", tmp_path / "state" / "state.json")
    monkeypatch.setattr(state, "PACKAGE_DIR", tmp_path / "state" / "packages")
    monkeypatch.setattr("dotfiles_setup.cli.state.STATE_FILE", tmp_path / "state" / "state.json")
    monkeypatch.setattr("dotfiles_setup.cli.state.PACKAGE_DIR", tmp_path / "state" / "packages")
    monkeypatch.setattr(overlay, "find_overlay_root", lambda: None)
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
