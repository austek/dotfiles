import json
import os
from datetime import UTC, datetime

import pytest
from dotfiles_setup import overlay
from dotfiles_setup.backends import InstallResult
from dotfiles_setup.claude_settings import _replace_settings_target
from dotfiles_setup.cli import main


def test_the_claude_settings_exist_before_the_install_steps_run(isolated_dotfiles, tmp_path, monkeypatch):
    seen = {}

    def run_install(inputs):
        seen["settings"] = (tmp_path / "claude-home" / "settings.json").is_file()
        return InstallResult(True, 0, "")

    monkeypatch.setattr("dotfiles_setup.install_flow.run_install", run_install)
    assert main(["install", "--preset", "homelab"]) == 0
    assert seen == {"settings": True}


def test_install_merges_the_preset_profile_into_the_generated_settings(isolated_dotfiles):
    dotfiles_dir, tmp_path = isolated_dotfiles
    (dotfiles_dir / "claude-profiles" / "claude_homelab.json").write_text(
        json.dumps({"enabledPlugins": {"sonarqube@official": True}})
    )
    assert main(["install", "--preset", "homelab"]) == 0
    generated = json.loads((tmp_path / "claude-home" / "settings.json").read_text())
    assert generated == {"model": "base", "enabledPlugins": {"sonarqube@official": True}}
    assert not (tmp_path / "state" / "claude-profiles").exists()


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

    monkeypatch.setattr("dotfiles_setup.fsutil.os.fdopen", failing_fdopen)
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


def test_install_expands_home_in_the_generated_env_and_its_drift_baseline(
    isolated_dotfiles, monkeypatch, tmp_path,
):
    dotfiles_dir, _ = isolated_dotfiles
    base = {"env": {"PATH": "$HOME/.local/bin:/usr/bin"}, "hooks": {"command": "$HOME/x"}}
    (dotfiles_dir / "claude" / ".claude" / "settings.json").write_text(json.dumps(base))
    monkeypatch.setattr("dotfiles_setup.env._home", lambda: tmp_path / "me")
    assert main(["install", "--preset", "homelab"]) == 0
    generated = (tmp_path / "claude-home" / "settings.json").read_text()
    assert json.loads(generated)["env"]["PATH"] == f"{tmp_path / 'me'}/.local/bin:/usr/bin"
    assert json.loads(generated)["hooks"] == {"command": "$HOME/x"}
    assert (tmp_path / "state" / "settings.last-generated.json").read_text() == generated
    assert main(["install", "--preset", "homelab"]) == 0


def test_rule016_install_stops_when_settings_were_edited_since_the_last_install(
    isolated_dotfiles, plugin_updates, foothold_syncs, tmp_path, capsys,
):
    settings = _install_then_edit_settings(tmp_path)
    edited = settings.read_text()
    assert main(["install", "--preset", "homelab"]) == 3
    assert settings.read_text() == edited
    assert not list(settings.parent.glob("settings.json.bak-*"))
    assert len(plugin_updates) == 1
    assert len(foothold_syncs) == 1
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


def test_rule016_dry_run_reports_settings_drift_and_continues(isolated_dotfiles, tmp_path, capsys):
    settings = _install_then_edit_settings(tmp_path)
    edited = settings.read_text()
    capsys.readouterr()
    assert main(["install", "--preset", "homelab", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "edited since the last install" in out
    assert '+  "hand": "edited"' in out
    assert settings.read_text() == edited


def test_settings_replacement_leaves_a_preexisting_shared_tmp_file_alone(tmp_path):
    target = tmp_path / "settings.json"
    target.write_text("old")
    other_install = tmp_path / "settings.json.tmp"
    other_install.write_text("in flight")
    _replace_settings_target(target, "new", datetime.now(UTC))
    assert target.read_text() == "new"
    assert other_install.read_text() == "in flight"
    assert sorted(p.name for p in tmp_path.glob("settings.json.*.tmp")) == []
