import subprocess
from pathlib import Path

import pytest
from dotfiles_setup import foothold
from dotfiles_setup.log import Logger

HOME = Path("/fake-home")
PROFILE = HOME / ".config/dotfiles/claude-profiles/claude_homelab.json"


@pytest.fixture(autouse=True)
def tools_present(monkeypatch):
    monkeypatch.setattr("dotfiles_setup.foothold.shutil.which", lambda tool: f"/usr/bin/{tool}")


def _recording_run(returncode=0, stderr=""):
    calls = []

    def run(argv, **_):
        calls.append(tuple(argv))
        return subprocess.CompletedProcess(argv, returncode, stdout="", stderr=stderr)

    return run, calls


def _install(tmp_path, preset="homelab", profile=PROFILE, dry_run=False, run=None):
    run = run or _recording_run()[0]
    foothold.install_foothold(Logger(dry_run=dry_run), preset, profile, unit_dir=tmp_path, home=HOME, run=run)


def test_names_append_the_preset_to_foothold():
    assert foothold.foothold_name("work") == "foothold-work"
    assert foothold.session_name("work") == "claude-foothold-work"
    assert foothold.unit_name("work") == "claude-foothold-work.service"


def test_unit_path_uses_the_home_specifier_under_home():
    assert foothold.unit_path_for(PROFILE, HOME) == "%h/.config/dotfiles/claude-profiles/claude_homelab.json"


def test_unit_path_keeps_paths_outside_home_absolute():
    assert foothold.unit_path_for(Path("/etc/claude.json"), HOME) == "/etc/claude.json"


def test_rendered_unit_launches_the_named_remote_control_session_with_the_profile():
    unit = foothold.render_unit("personal", "%h/p.json")
    assert "--remote-control foothold-personal --settings %h/p.json" in unit
    assert "tmux new-session -d -s claude-foothold-personal" in unit


def test_rendered_unit_waits_for_connectivity_before_launching():
    unit = foothold.render_unit("personal", "%h/p.json")
    assert unit.index("ExecStartPre=") < unit.index("ExecStart=/bin/sh")
    assert foothold.NETWORK_PROBE_URL in unit
    assert "TimeoutStartSec=180" in unit


def test_rendered_unit_retries_after_a_failed_connectivity_probe():
    unit = foothold.render_unit("personal", "%h/p.json")
    assert "Restart=on-failure" in unit
    assert "RestartSec=30" in unit


def test_rendered_unit_puts_the_sonarqube_cli_on_path():
    assert "%h/.local/share/sonarqube-cli/bin" in foothold.render_unit("personal", "%h/p.json")


def test_rendered_unit_hardcodes_no_home_directory():
    assert "/home/" not in foothold.render_unit("personal", "%h/p.json")


def test_install_writes_the_unit_enables_linger_and_starts_it(tmp_path):
    run, calls = _recording_run()
    _install(tmp_path, run=run)
    assert (tmp_path / "claude-foothold-homelab.service").is_file()
    assert calls == [
        ("loginctl", "enable-linger"),
        ("systemctl", "--user", "daemon-reload"),
        ("systemctl", "--user", "enable", "--now", "claude-foothold-homelab.service"),
    ]


def test_install_is_idempotent(tmp_path):
    _install(tmp_path)
    unit = tmp_path / "claude-foothold-homelab.service"
    before = unit.stat().st_mtime_ns
    _install(tmp_path)
    assert unit.stat().st_mtime_ns == before


def test_install_rewrites_a_stale_unit(tmp_path):
    unit = tmp_path / "claude-foothold-homelab.service"
    unit.write_text("stale")
    _install(tmp_path)
    assert "stale" not in unit.read_text()


def test_install_does_nothing_for_a_preset_without_a_claude_profile(tmp_path):
    run, calls = _recording_run()
    _install(tmp_path, profile=None, run=run)
    assert calls == [] and list(tmp_path.iterdir()) == []


def test_dry_run_changes_nothing(tmp_path, capsys):
    run, calls = _recording_run()
    _install(tmp_path, dry_run=True, run=run)
    assert calls == [] and list(tmp_path.iterdir()) == []
    assert "claude-foothold-homelab.service" in capsys.readouterr().out


def test_missing_tmux_or_systemctl_warns_and_skips(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("dotfiles_setup.foothold.shutil.which", lambda tool: None if tool == "tmux" else "/bin/x")
    run, calls = _recording_run()
    _install(tmp_path, run=run)
    assert calls == [] and list(tmp_path.iterdir()) == []
    assert "tmux not found" in capsys.readouterr().out


def test_a_failing_command_warns_without_raising(tmp_path, capsys):
    _install(tmp_path, run=_recording_run(returncode=1, stderr="no bus")[0])
    assert "no bus" in capsys.readouterr().out


def test_an_unwritable_unit_dir_warns_without_raising(tmp_path, capsys):
    blocker = tmp_path / "file"
    blocker.write_text("")
    _install(blocker)
    assert "Could not set up foothold-homelab" in capsys.readouterr().out
