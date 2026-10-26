import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from dotfiles_setup import claude_profile as cp
from dotfiles_setup import tools
from dotfiles_setup.log import Logger


def make(tmp_path, dry_run=False):
    home = tmp_path / "home"
    home.mkdir()
    t = tools.Tooling(Logger(dry_run=dry_run, verbosity=1), home, run=lambda *a, **k: SimpleNamespace(returncode=0))
    return t, home, tmp_path / "profiles"


def read_aliases(home):
    return (home / ".zshrc.profile").read_text()


def test_a_dry_run_writes_nothing(tmp_path):
    t, home, profiles = make(tmp_path, dry_run=True)
    cp.configure_claude_profile(t, "work", profiles)
    assert list(home.iterdir()) == []


@pytest.mark.parametrize("preset", ["work", "homelab", "personal", "custom"])
def test_the_plain_claude_alias_follows_the_preset(tmp_path, preset):
    t, home, profiles = make(tmp_path)
    cp.configure_claude_profile(t, preset, profiles)
    kind = preset if preset in ("work", "homelab") else "personal"
    expected = f"alias claude='claude-tmux {kind} claude --settings \"{profiles}/claude_{kind}.json\"'"
    assert expected in read_aliases(home).splitlines()


def test_every_profile_gets_an_alias_and_burst_uses_its_own_config_dir(tmp_path):
    t, home, profiles = make(tmp_path)
    cp.configure_claude_profile(t, "work", profiles)
    aliases = read_aliases(home)
    for name in ("work", "personal", "homelab"):
        assert f"alias claude-{name}='claude-tmux {name} claude --settings \"{profiles}/claude_{name}.json\"'" in aliases
    burst = home / ".claude-burst"
    assert f"alias claude-burst='claude-tmux burst env CLAUDE_CONFIG_DIR=\"{burst}\" claude --settings \"{profiles}/claude_burst.json\"'" in aliases
    assert aliases.splitlines()[0].startswith("# --- Claude Code profiles")
    assert aliases.splitlines()[-1] == "# --- End Claude Code profile ---"


def test_the_burst_dir_links_everything_except_credentials_and_backups(tmp_path):
    t, home, profiles = make(tmp_path)
    claude = home / ".claude"
    claude.mkdir()
    for name in ("settings.json", ".hidden", ".credentials.json"):
        (claude / name).write_text("")
    (claude / "backups").mkdir()
    cp.configure_claude_profile(t, "work", profiles)
    burst = home / ".claude-burst"
    assert sorted(p.name for p in burst.iterdir()) == [".hidden", "settings.json"]
    assert (burst / "settings.json").resolve() == (claude / "settings.json").resolve()


def test_a_rerun_refreshes_existing_burst_links(tmp_path):
    t, home, profiles = make(tmp_path)
    claude = home / ".claude"
    claude.mkdir()
    (claude / "a").write_text("")
    cp.configure_claude_profile(t, "work", profiles)
    cp.configure_claude_profile(t, "work", profiles)
    assert (home / ".claude-burst/a").is_symlink()


def test_the_wrapper_applies_the_machine_profile_and_is_executable(tmp_path):
    t, home, profiles = make(tmp_path)
    cp.configure_claude_profile(t, "homelab", profiles)
    wrapper = home / "bin/claude"
    text = wrapper.read_text()
    assert f'exec "$real" --settings "{profiles}/claude_homelab.json" "$@"' in text
    assert "Applies the homelab profile" in text
    assert wrapper.stat().st_mode & 0o111


def test_the_wrapper_skips_itself_and_execs_the_next_claude_on_path(tmp_path):
    t, home, profiles = make(tmp_path)
    cp.configure_claude_profile(t, "work", profiles)
    real_dir = tmp_path / "real"
    real_dir.mkdir()
    real = real_dir / "claude"
    real.write_text('#!/bin/sh\necho "$@"\n')
    real.chmod(0o755)
    env = {"PATH": f"{home / 'bin'}:{real_dir}:/usr/bin:/bin"}
    out = subprocess.run([str(home / "bin/claude"), "hello"], env=env, capture_output=True, text=True, check=True)
    assert out.stdout.strip() == f"--settings {profiles}/claude_work.json hello"


def test_the_wrapper_reports_a_missing_claude_binary(tmp_path):
    t, home, profiles = make(tmp_path)
    cp.configure_claude_profile(t, "work", profiles)
    result = subprocess.run(
        [str(home / "bin/claude")], env={"PATH": f"{home / 'bin'}:/usr/bin:/bin"},
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 127
    assert "no claude binary found" in result.stderr


def test_the_session_path_file_puts_the_wrapper_first(tmp_path):
    t, home, profiles = make(tmp_path)
    cp.configure_claude_profile(t, "work", profiles)
    env_file = home / ".config/environment.d/zz-claude-profile.conf"
    assert env_file.read_text().splitlines()[1] == f"PATH={home}/bin:{home}/.local/bin:${{PATH}}"


def test_the_burst_exclusions_are_the_auth_files():
    assert cp.BURST_EXCLUDED == {".credentials.json", "backups"}


def test_a_home_without_claude_config_still_gets_the_burst_dir(tmp_path):
    t, home, profiles = make(tmp_path)
    cp.configure_claude_profile(t, "work", profiles)
    assert Path(home / ".claude-burst").is_dir()
