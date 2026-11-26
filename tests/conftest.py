import json
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "bin"))
sys.path.insert(0, str(_ROOT / "local" / ".local" / "bin"))

from cli_support import stub_subprocess
from dotfiles_setup import overlay, state
from dotfiles_setup.backends import InstallResult


@pytest.fixture(autouse=True)
def isolated_home(tmp_path_factory, monkeypatch):
    """Points HOME and every overlay location at a throwaway home, so no test can touch a real overlay checkout."""
    home = tmp_path_factory.mktemp("home")
    monkeypatch.setenv("HOME", str(home))
    for variable in (overlay.OVERLAY_ROOT_VARIABLE, overlay.LEGACY_ROOT_VARIABLE):
        monkeypatch.delenv(variable, raising=False)
    monkeypatch.setattr(overlay, "DEFAULT_OVERLAY_ROOT", home / ".dotfiles-overlay")
    monkeypatch.setattr(overlay, "LEGACY_OVERLAY_ROOT", home / ".dotfiles-private")
    monkeypatch.setattr(overlay, "LOCAL_OVERLAY_ROOT", home / ".config" / "dotfiles" / "local-overlay")


@pytest.fixture(autouse=True)
def syslog_lines(monkeypatch):
    """Captures what would reach syslog, so a test run never writes to the host's log."""
    lines = []
    monkeypatch.setattr("dotfiles_setup.log.syslog.syslog", lambda priority, message: lines.append((priority, message)))
    monkeypatch.setattr("dotfiles_setup.log.syslog.openlog", lambda *args, **kwargs: None)
    return lines


@pytest.fixture(autouse=True)
def no_network_tool_fetch(monkeypatch):
    def refuse(url, *_args):
        raise AssertionError(f"test attempted a real network call: {url}")

    for name in ("fetch_https", "fetch_bytes_https", "download_https", "redirect_location"):
        monkeypatch.setattr(f"dotfiles_setup.tooling.{name}", refuse)


@pytest.fixture
def no_core_packages(monkeypatch):
    """Tests of the package plan name their own packages; the core list would add host-dependent ones."""
    monkeypatch.setattr("dotfiles_setup.system_steps.CORE_PACKAGES", ())


@pytest.fixture
def converged(monkeypatch):
    """Pins every host-dependent plan predicate to 'nothing to do', so a plan is empty unless a test adds work."""
    monkeypatch.setattr("dotfiles_setup.desktop_defaults.shell_change_pending", lambda: False)
    monkeypatch.setattr("dotfiles_setup.desktop_defaults.ibus_hotkey_pending", lambda t: False)
    monkeypatch.setattr("dotfiles_setup.system_check.pending_releases", lambda ctx: [])
    monkeypatch.setattr("dotfiles_setup.secrets_env.pending", lambda home: ())
    monkeypatch.setattr("dotfiles_setup.terminfo.pending", lambda t: ())
    monkeypatch.setattr("dotfiles_setup.system_check.snapd_reason", lambda installed: None)
    monkeypatch.setattr("dotfiles_setup.system_steps.docker_group_pending", lambda ctx: False)
    monkeypatch.setattr("dotfiles_setup.zsh_cache.pending", lambda home: False)
    monkeypatch.setattr("dotfiles_setup.uninstallers.pending", lambda t, names: ())


@pytest.fixture
def plugin_updates(monkeypatch):
    calls = []
    monkeypatch.setattr("dotfiles_setup.claude_plugins.update_claude_plugins", lambda logger, settings: calls.append(logger))
    return calls


@pytest.fixture
def doctor_reports(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "dotfiles_setup.doctor_cmd.report_after_apply",
        lambda t, packages, env, *, dry_run: calls.append((tuple(sorted(packages)), dry_run)),
    )
    return calls


@pytest.fixture
def foothold_syncs(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "dotfiles_setup.foothold.sync_footholds",
        lambda logger, wanted, path_entries: calls.append(wanted),
    )
    return calls


@pytest.fixture
def flow_calls(monkeypatch):
    """Replaces the real install steps (sudo, apt, stow) with a recorder that succeeds."""
    calls = []

    def run_install(inputs):
        calls.append(inputs)
        return InstallResult(True, 0, "")

    monkeypatch.setattr("dotfiles_setup.install_flow.run_install", run_install)
    return calls


@pytest.fixture
def isolated_dotfiles(tmp_path, monkeypatch, flow_calls, plugin_updates, foothold_syncs, doctor_reports):
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
        "footholds": ["main", "burst"],
    }))
    (dotfiles_dir / "presets" / "work.json").write_text(json.dumps({"package_files": ["apt_common.txt"]}))
    (dotfiles_dir / "packages" / "apt_common.txt").write_text("zsh\ncurl\n")
    (dotfiles_dir / "packages" / "path_dirs.txt").write_text("~/.local/bin\n/usr/bin\n")
    (dotfiles_dir / "claude-profiles" / "claude_homelab.json").write_text("{}")

    (dotfiles_dir / "claude" / ".claude").mkdir(parents=True)
    (dotfiles_dir / "claude" / ".claude" / "settings.json").write_text(json.dumps({"model": "base"}))

    monkeypatch.setattr("dotfiles_setup.env._dotfiles_dir", lambda: dotfiles_dir)
    monkeypatch.setattr("dotfiles_setup.env._claude_home", lambda: tmp_path / "claude-home")
    monkeypatch.setattr(state, "state_dir", lambda: tmp_path / "state")
    monkeypatch.setattr(overlay, "find_overlay_root", lambda: None)
    monkeypatch.setattr("dotfiles_setup.system_steps.CORE_PACKAGES", ())
    monkeypatch.setattr("dotfiles_setup.install_cmd.confirm_plan", lambda *a, **kw: None)
    monkeypatch.setattr("dotfiles_setup.update.pull_if_behind", lambda *a, **kw: False)
    monkeypatch.setattr("dotfiles_setup.identity.ensure_git_identity", lambda **kw: tmp_path / "gitconfig.local")
    stub_subprocess(monkeypatch)
    return dotfiles_dir, tmp_path
