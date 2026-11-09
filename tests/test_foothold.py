import os
import subprocess
from pathlib import Path

import pytest
from dotfiles_setup import foothold
from dotfiles_setup.log import Logger


@pytest.fixture(autouse=True)
def tools_present(monkeypatch):
    monkeypatch.setattr("dotfiles_setup.foothold.shutil.which", lambda tool: f"/usr/bin/{tool}")


def _recording_run(returncode=0, stderr="", fail_on=None):
    calls = []

    def run(argv, **_):
        calls.append(tuple(argv))
        code = returncode if fail_on in (None, argv[0]) else 0
        return subprocess.CompletedProcess(argv, code, stdout="", stderr=stderr)

    return run, calls


def _install(tmp_path, account="main", dry_run=False, run=None, burst_dir=None):
    run = run or _recording_run()[0]
    return foothold.install_foothold(
        Logger(dry_run=dry_run), account, unit_dir=tmp_path, run=run, burst_dir=burst_dir or tmp_path / "no-burst",
    )


def _logged_in_burst(tmp_path):
    burst = tmp_path / "burst"
    burst.mkdir(exist_ok=True)
    (burst / ".credentials.json").write_text("{}")
    return burst


def test_main_names_are_plain_foothold_and_the_hostname():
    assert foothold.session_name("main") == "claude-foothold"
    assert foothold.unit_name("main") == "claude-foothold.service"
    assert foothold.remote_control_name("main") == "%H"


def test_burst_names_append_burst():
    assert foothold.session_name("burst") == "claude-foothold-burst"
    assert foothold.unit_name("burst") == "claude-foothold-burst.service"
    assert foothold.remote_control_name("burst") == "%H-burst"


def test_rendered_main_unit_names_the_remote_control_session_after_the_hostname():
    unit = foothold.render_unit("main")
    assert _exec_start(unit).endswith("claude-foothold-launch --start claude-foothold %h/Workspace %H")
    assert "--settings" not in unit


def test_rendered_burst_unit_runs_the_burst_account_as_hostname_burst():
    unit = foothold.render_unit("burst")
    assert _exec_start(unit).endswith("--start claude-foothold-burst %h/Workspace %H-burst burst")
    assert "ExecStop=-/usr/bin/env tmux kill-session -t =claude-foothold-burst\n" in unit


def _exec_start(unit):
    return next(line for line in unit.splitlines() if line.startswith("ExecStart="))


@pytest.mark.parametrize("account", foothold.ACCOUNTS)
def test_sec012_rendered_unit_has_no_shell_string(account):
    unit = foothold.render_unit(account)
    line = _exec_start(unit)
    assert "sh -c" not in unit and "/bin/sh" not in unit and "bash" not in line
    assert not any(token in line for token in (";", "|", "&&", "`", "$("))
    command = line.removeprefix("ExecStart=")
    assert command.startswith("%h/.dotfiles/bin/claude-foothold-launch --start ")


def test_rendered_unit_waits_for_connectivity_before_launching():
    unit = foothold.render_unit("main")
    assert unit.index("ExecStartPre=") < unit.index("ExecStart=")
    assert foothold.NETWORK_PROBE_URL in unit
    assert "TimeoutStartSec=300" in unit


def test_rendered_unit_starts_the_session_in_the_workspace_directory():
    assert " %h/Workspace " in _exec_start(foothold.render_unit("main"))


def test_rendered_unit_resolves_curl_through_path():
    assert "ExecStartPre=/usr/bin/env curl " in foothold.render_unit("main")


def test_rendered_unit_retries_after_a_failed_connectivity_probe():
    unit = foothold.render_unit("main")
    assert "Restart=on-failure" in unit
    assert "RestartSec=30" in unit


def test_rendered_unit_puts_the_sonarqube_cli_on_path():
    assert "%h/.local/share/sonarqube-cli/bin" in foothold.render_unit("main")


@pytest.mark.parametrize("account", foothold.ACCOUNTS)
def test_rendered_unit_reads_no_secrets_file(account):
    unit = foothold.render_unit(account)
    assert "EnvironmentFile" not in unit
    assert "secrets.env" not in unit


def test_rendered_unit_launches_claude_through_the_launcher():
    unit = foothold.render_unit("main")
    assert "%h/.dotfiles/bin/claude-foothold-launch" in unit
    assert "claude --remote-control" not in unit


def _installed_unit(tmp_path, account="main", content=None):
    unit = tmp_path / foothold.unit_name(account)
    unit.write_text(foothold.render_unit(account) if content is None else content)
    return unit


def _restart(tmp_path, account="main", dry_run=False, run=None):
    run = run or _recording_run()[0]
    return foothold.restart_foothold(Logger(dry_run=dry_run), account, unit_dir=tmp_path, run=run)


PROBE = ("curl", "-s", "--max-time", "5", "-o", "/dev/null", foothold.NETWORK_PROBE_URL)
RELOAD = ("systemctl", "--user", "daemon-reload")
RESTART = ("systemd-run", "--user", "--wait", "--collect", "--quiet", "--", "systemctl", "--user", "restart", "claude-foothold.service")


def test_restart_probes_the_network_then_reloads_and_restarts_without_touching_tmux(tmp_path):
    _installed_unit(tmp_path)
    run, calls = _recording_run()
    assert _restart(tmp_path, run=run) is True
    assert calls == [PROBE, RELOAD, RESTART]


def test_rendered_unit_ends_the_session_only_on_stop_never_on_start():
    unit = foothold.render_unit("main")
    assert "ExecStop=-/usr/bin/env tmux kill-session -t =claude-foothold\n" in unit
    assert "ExecStartPre=-" not in unit
    assert "--start claude-foothold " in unit


def test_restart_rewrites_a_stale_unit_and_reloads_before_restarting(tmp_path):
    unit = _installed_unit(tmp_path, content="[Service]\nExecStart=old\n")
    run, calls = _recording_run()
    assert _restart(tmp_path, run=run) is True
    assert unit.read_text() == foothold.render_unit("main")
    assert calls == [PROBE, RELOAD, RESTART]


@pytest.mark.parametrize("content", ["stale", None])
def test_restart_does_not_restart_when_the_reload_fails(tmp_path, content):
    _installed_unit(tmp_path, content=content)
    run, calls = _recording_run(returncode=1, fail_on="systemctl")
    assert _restart(tmp_path, run=run) is False
    assert calls == [PROBE, RELOAD]


def test_restart_leaves_the_unit_and_session_alone_when_the_network_is_down(tmp_path):
    unit = _installed_unit(tmp_path, content="stale")
    run, calls = _recording_run(returncode=1, fail_on="curl")
    assert _restart(tmp_path, run=run) is False
    assert calls == [PROBE]
    assert unit.read_text() == "stale"


def test_restart_warns_instead_of_raising_when_systemctl_cannot_launch(tmp_path, capsys):
    _installed_unit(tmp_path)

    def run(argv, **_):
        raise PermissionError("denied")

    assert _restart(tmp_path, run=run) is False
    assert "Could not restart" in capsys.readouterr().out


def test_restart_without_an_installed_unit_warns_and_runs_nothing(tmp_path, capsys):
    run, calls = _recording_run()
    assert _restart(tmp_path, run=run) is False
    assert calls == []
    assert "dotfiles-setup install" in capsys.readouterr().out


def test_restart_dry_run_runs_nothing(tmp_path):
    _installed_unit(tmp_path)
    run, calls = _recording_run()
    assert _restart(tmp_path, dry_run=True, run=run) is True
    assert calls == []


def test_restart_reports_failure_when_systemctl_fails(tmp_path, capsys):
    _installed_unit(tmp_path)
    assert _restart(tmp_path, run=_recording_run(returncode=1, stderr="no bus", fail_on="systemctl")[0]) is False
    assert "no bus" in capsys.readouterr().out


def _run_launcher(tmp_path, claude_script, args, secrets=None, secrets_mode=0o600):
    home = tmp_path / "home"
    (home / ".config/dotfiles").mkdir(parents=True)
    if secrets is not None:
        secrets_file = home / ".config/dotfiles/secrets.env"
        secrets_file.write_text(secrets)
        secrets_file.chmod(secrets_mode)
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    claude = fake_bin / "claude"
    claude.write_text(f"#!/bin/sh\n{claude_script}\n")
    claude.chmod(0o755)
    launcher = Path(__file__).parent.parent / "bin" / "claude-foothold-launch"
    result = subprocess.run(
        [str(launcher), *args],
        env={"HOME": str(home), "PATH": f"{fake_bin}:/usr/bin:/bin"},
        capture_output=True, text=True, check=True, cwd=tmp_path,
    )
    return result.stdout.strip()


def test_launcher_exports_secrets_to_claude(tmp_path):
    out = _run_launcher(tmp_path, 'echo "$FOO|$1|$2|$3"', ["foothold-x"], secrets="FOO='bar baz'\n")
    assert out == "bar baz|--remote-control|foothold-x|"


def test_rule029_launcher_ignores_group_readable_secrets(tmp_path):
    out = _run_launcher(tmp_path, 'echo "[$FOO]"', ["n"], secrets="FOO=leak\n", secrets_mode=0o644)
    assert out == "[]"


def _launch_with_secrets_node(tmp_path, prepare, fake_uid=None):
    home = tmp_path / "home"
    (home / ".config/dotfiles").mkdir(parents=True)
    prepare(home / ".config/dotfiles/secrets.env")
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    if fake_uid is not None:
        fake_id = fake_bin / "id"
        fake_id.write_text(f"#!/bin/sh\necho {fake_uid}\n")
        fake_id.chmod(0o755)
    claude = fake_bin / "claude"
    claude.write_text('#!/bin/sh\necho "[$FOO]"\n')
    claude.chmod(0o755)
    launcher = Path(__file__).parent.parent / "bin" / "claude-foothold-launch"
    return subprocess.run(
        [str(launcher), "n"], env={"HOME": str(home), "PATH": f"{fake_bin}:/usr/bin:/bin"},
        capture_output=True, text=True, check=True, cwd=tmp_path,
    )


def _file(mode):
    def prepare(path):
        path.write_text("FOO=leak\n")
        path.chmod(mode)
    return prepare


@pytest.mark.parametrize("mode", [0o640, 0o604, 0o644, 0o660, 0o606])
def test_rule029_launcher_skips_and_warns_for_any_group_or_other_access(tmp_path, mode):
    result = _launch_with_secrets_node(tmp_path, _file(mode))
    assert result.stdout.strip() == "[]"
    assert "secrets.env skipped: group/other can access it" in result.stderr


@pytest.mark.parametrize("mode", [0o600, 0o400])
def test_rule029_launcher_loads_owner_only_secrets_without_warning(tmp_path, mode):
    result = _launch_with_secrets_node(tmp_path, _file(mode))
    assert result.stdout.strip() == "[leak]"
    assert "skipped" not in result.stderr


def test_rule029_launcher_skips_a_symlink_to_a_group_readable_file(tmp_path):
    def prepare(path):
        target = tmp_path / "target.env"
        _file(0o640)(target)
        path.symlink_to(target)
    result = _launch_with_secrets_node(tmp_path, prepare)
    assert result.stdout.strip() == "[]"
    assert "skipped" in result.stderr


def test_rule029_launcher_skips_a_file_owned_by_another_user(tmp_path):
    result = _launch_with_secrets_node(tmp_path, _file(0o600), fake_uid=os.geteuid() + 1)
    assert result.stdout.strip() == "[]"
    assert f"secrets.env skipped: owned by uid {os.geteuid()}" in result.stderr


def test_rule029_launcher_skips_a_non_regular_file(tmp_path):
    def prepare(path):
        path.mkdir()
        path.chmod(0o700)
    result = _launch_with_secrets_node(tmp_path, prepare)
    assert result.stdout.strip() == "[]"
    assert "not a regular file" in result.stderr


def test_rule029_launcher_parses_secrets_as_data_not_shell(tmp_path):
    secrets = (
        "# comment\n\nPLAIN=abc def\nTICK=`touch pwned`$(touch pwned)\nDQ=\"x y\"\nSQ='p q'\n1BAD=no\n"
        "PADDED=  ' keep me '  \nTRAILING='abc' \nNO_NEWLINE=last"
    )
    out = _run_launcher(
        tmp_path, 'echo "$PLAIN|$TICK|$DQ|$SQ|$PADDED|$TRAILING|$NO_NEWLINE"', ["n"], secrets=secrets,
    )
    assert out == "abc def|`touch pwned`$(touch pwned)|x y|p q| keep me |abc|last"
    assert not (tmp_path / "pwned").exists()


def test_launcher_runs_claude_without_a_secrets_file(tmp_path):
    assert _run_launcher(tmp_path, "echo ok", ["n"]) == "ok"


def test_launcher_runs_the_burst_account_with_its_config_dir(tmp_path):
    out = _run_launcher(tmp_path, 'echo "$CLAUDE_CONFIG_DIR|$1|$2"', ["host-burst", "burst"])
    burst = tmp_path / "home" / ".claude-burst"
    assert out == f"{burst}|--remote-control|host-burst"
    assert burst.is_dir()


def _run_start(tmp_path, args, session_exists, new_session_rc=0, with_tmux=True, secrets=None, secrets_mode=0o600):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    if with_tmux:
        tmux = fake_bin / "tmux"
        tmux.write_text(
            '#!/bin/sh\nfor a in "$@"; do printf "%s\\n" "$a"; done >> "$TMUX_LOG"; printf -- "--\\n" >> "$TMUX_LOG"\n'
            f'[ "$1" != has-session ] || exit {0 if session_exists else 1}\n'
            f'[ "$1" != new-session ] || exit {new_session_rc}\n'
        )
        tmux.chmod(0o755)
    if secrets is not None:
        (tmp_path / ".config/dotfiles").mkdir(parents=True)
        secrets_file = tmp_path / ".config/dotfiles/secrets.env"
        secrets_file.write_text(secrets)
        secrets_file.chmod(secrets_mode)
    log = tmp_path / "tmux.log"
    launcher = Path(__file__).parent.parent / "bin" / "claude-foothold-launch"
    result = subprocess.run(
        [str(launcher), "--start", *args],
        env={"HOME": str(tmp_path), "PATH": str(fake_bin) if not with_tmux else f"{fake_bin}:/usr/bin:/bin",
             "TMUX_LOG": str(log)},
        capture_output=True, text=True, check=False,
    )
    calls = [c.split("\n") for c in log.read_text().split("--\n") if c] if log.exists() else []
    return result, calls


def test_start_creates_a_detached_session_in_the_directory_running_the_launcher(tmp_path):
    result, calls = _run_start(tmp_path, ["sess", "/work dir", "host", "burst"], session_exists=False)
    launcher = str(Path(__file__).parent.parent / "bin" / "claude-foothold-launch")
    assert result.returncode == 0
    assert calls[1][:-1] == ["new-session", "-d", "-s", "sess", "-c", "/work dir", launcher, "host", "burst"]


def test_start_is_a_no_op_success_while_the_session_exists(tmp_path):
    result, calls = _run_start(tmp_path, ["sess", "/w", "host"], session_exists=True)
    assert result.returncode == 0
    assert [c[0] for c in calls] == ["has-session"]
    assert calls[0][:3] == ["has-session", "-t", "=sess"]


def test_start_rejects_a_wrong_argument_count(tmp_path):
    result, calls = _run_start(tmp_path, ["sess"], session_exists=False)
    assert result.returncode == 2
    assert calls == []


def test_start_fails_clearly_when_tmux_is_absent(tmp_path):
    result, _ = _run_start(tmp_path, ["sess", "/w", "host"], session_exists=False, with_tmux=False)
    assert result.returncode == 127
    assert "tmux not found" in result.stderr


def test_start_propagates_a_failing_new_session(tmp_path):
    result, _ = _run_start(tmp_path, ["sess", "/w", "host"], session_exists=False, new_session_rc=1)
    assert result.returncode == 1


def test_start_treats_a_failing_has_session_as_no_session(tmp_path):
    result, calls = _run_start(tmp_path, ["sess", "/w", "host"], session_exists=False)
    assert result.returncode == 0
    assert [c[0] for c in calls] == ["has-session", "new-session"]


def test_start_warns_to_stderr_about_a_missing_secrets_file_and_still_starts(tmp_path):
    result, calls = _run_start(tmp_path, ["sess", "/w", "host"], session_exists=False)
    assert "secrets.env not found or unreadable" in result.stderr
    assert calls[-1][0] == "new-session"


def test_start_warns_to_stderr_about_unsafe_secrets_and_still_starts(tmp_path):
    result, calls = _run_start(tmp_path, ["sess", "/w", "host"], session_exists=False, secrets="A=b\n", secrets_mode=0o644)
    assert "claude-foothold-launch: secrets.env skipped: group/other can access it (mode 644)" in result.stderr
    assert result.returncode == 0
    assert calls[-1][0] == "new-session"


def test_start_is_silent_about_a_safe_secrets_file(tmp_path):
    result, _ = _run_start(tmp_path, ["sess", "/w", "host"], session_exists=False, secrets="A=b\n")
    assert result.stderr == ""


def test_start_is_a_no_op_while_an_old_style_session_exists(tmp_path):
    result, calls = _run_start(tmp_path, ["claude-foothold", "/w", "host"], session_exists=True)
    assert result.returncode == 0
    assert [c[0] for c in calls] == ["has-session"]


OLD_UNIT = (
    "[Service]\nType=oneshot\nEnvironmentFile=-%h/.config/dotfiles/secrets.env\n"
    "ExecStart=/bin/sh -c 'tmux has-session -t =claude-foothold 2>/dev/null || exec tmux new-session -d "
    "-s claude-foothold -c \"%h/Workspace\" %h/.dotfiles/bin/claude-foothold-launch %H'\n"
)


def _assert_upgraded(unit, account, calls):
    text = unit.read_text()
    assert text == foothold.render_unit(account)
    assert "EnvironmentFile" not in text and "sh -c" not in text
    assert ("systemctl", "--user", "daemon-reload") in calls


def test_install_upgrades_the_previous_unit_text(tmp_path):
    unit = _installed_unit(tmp_path, content=OLD_UNIT)
    run, calls = _recording_run()
    _install(tmp_path, run=run)
    _assert_upgraded(unit, "main", calls)
    assert ("systemctl", "--user", "enable", "--now", "claude-foothold.service") in calls


def test_restart_upgrades_the_previous_unit_text_then_restarts(tmp_path):
    unit = _installed_unit(tmp_path, content=OLD_UNIT)
    run, calls = _recording_run()
    assert _restart(tmp_path, run=run) is True
    _assert_upgraded(unit, "main", calls)
    assert calls[-1] == RESTART


def test_launcher_runs_the_main_account_without_a_config_dir(tmp_path):
    assert _run_launcher(tmp_path, 'echo "[${CLAUDE_CONFIG_DIR-}]"', ["host"]) == "[]"


@pytest.mark.parametrize("account", foothold.ACCOUNTS)
def test_rendered_unit_hardcodes_no_home_directory(account):
    assert "/home/" not in foothold.render_unit(account)


def test_install_writes_the_unit_enables_linger_and_starts_it(tmp_path):
    run, calls = _recording_run()
    _install(tmp_path, run=run)
    assert (tmp_path / "claude-foothold.service").is_file()
    assert calls == [
        ("loginctl", "enable-linger"),
        ("systemctl", "--user", "daemon-reload"),
        ("systemctl", "--user", "enable", "--now", "claude-foothold.service"),
    ]


def test_install_skips_the_burst_unit_until_the_burst_account_has_logged_in(tmp_path, capsys):
    run, calls = _recording_run()
    assert _install(tmp_path, account="burst", run=run) is False
    assert calls == []
    assert not (tmp_path / "claude-foothold-burst.service").exists()
    assert "claude-burst" in capsys.readouterr().out


def test_install_sets_up_the_burst_unit_once_logged_in(tmp_path):
    run, calls = _recording_run()
    assert _install(tmp_path, account="burst", run=run, burst_dir=_logged_in_burst(tmp_path)) is True
    assert (tmp_path / "claude-foothold-burst.service").read_text() == foothold.render_unit("burst")
    assert calls[-1] == ("systemctl", "--user", "enable", "--now", "claude-foothold-burst.service")


def test_install_is_idempotent(tmp_path):
    _install(tmp_path)
    unit = tmp_path / "claude-foothold.service"
    os.utime(unit, ns=(0, 0))
    _install(tmp_path)
    assert unit.stat().st_mtime_ns == 0


def test_install_rewrites_a_stale_unit(tmp_path):
    unit = tmp_path / "claude-foothold.service"
    unit.write_text("stale")
    _install(tmp_path)
    assert "stale" not in unit.read_text()


def test_retire_disables_ends_the_session_and_removes_the_unit(tmp_path):
    _install(tmp_path, account="burst", burst_dir=_logged_in_burst(tmp_path))
    run, calls = _recording_run()
    foothold.retire_foothold(Logger(dry_run=False), "burst", unit_dir=tmp_path, run=run)
    assert calls == [
        ("systemctl", "--user", "disable", "--now", "claude-foothold-burst.service"),
        ("tmux", "kill-session", "-t", "=claude-foothold-burst"),
        ("systemctl", "--user", "daemon-reload"),
    ]
    assert not (tmp_path / "claude-foothold-burst.service").exists()


def test_retire_is_a_no_op_without_that_unit(tmp_path):
    run, calls = _recording_run()
    foothold.retire_foothold(Logger(dry_run=False), "main", unit_dir=tmp_path, run=run)
    assert calls == []


def test_retire_dry_run_changes_nothing(tmp_path):
    _install(tmp_path)
    run, calls = _recording_run()
    foothold.retire_foothold(Logger(dry_run=True), "main", unit_dir=tmp_path, run=run)
    assert calls == []
    assert (tmp_path / "claude-foothold.service").is_file()


def test_retire_legacy_removes_every_preset_named_unit_and_session(tmp_path):
    for preset in ("work", "homelab"):
        (tmp_path / f"claude-foothold-{preset}.service").write_text("old")
    run, calls = _recording_run()
    foothold.retire_legacy_footholds(Logger(dry_run=False), unit_dir=tmp_path, run=run)
    assert ("tmux", "kill-session", "-t", "=claude-foothold-work") in calls
    assert ("tmux", "kill-session", "-t", "=claude-foothold-homelab") in calls
    assert _units(tmp_path) == []


def test_retire_legacy_never_touches_an_account_unit(tmp_path):
    _installed_unit(tmp_path, "main")
    _installed_unit(tmp_path, "burst")
    run, calls = _recording_run()
    foothold.retire_legacy_footholds(Logger(dry_run=False), unit_dir=tmp_path, run=run)
    assert calls == []
    assert _units(tmp_path) == ["claude-foothold-burst.service", "claude-foothold.service"]


def _sync(tmp_path, wanted, run=None, burst_dir=None):
    run = run or _recording_run()[0]
    foothold.sync_footholds(
        Logger(dry_run=False), wanted, unit_dir=tmp_path, run=run, burst_dir=burst_dir or tmp_path / "no-burst",
    )


def _units(tmp_path):
    return sorted(p.name for p in tmp_path.glob("*.service"))


def test_sync_installs_both_accounts_and_retires_the_legacy_unit(tmp_path):
    (tmp_path / "claude-foothold-homelab.service").write_text("old")
    _sync(tmp_path, ("main", "burst"), burst_dir=_logged_in_burst(tmp_path))
    assert _units(tmp_path) == ["claude-foothold-burst.service", "claude-foothold.service"]


def test_sync_without_a_burst_login_still_installs_main_and_retires_the_legacy_unit(tmp_path):
    (tmp_path / "claude-foothold-homelab.service").write_text("old")
    _sync(tmp_path, ("main", "burst"))
    assert _units(tmp_path) == ["claude-foothold.service"]


def test_sync_with_no_footholds_retires_every_unit(tmp_path):
    for name in ("claude-foothold.service", "claude-foothold-burst.service", "claude-foothold-work.service"):
        (tmp_path / name).write_text("old")
    _sync(tmp_path, ())
    assert _units(tmp_path) == []


def test_sync_keeps_the_legacy_unit_when_main_fails_to_install(tmp_path):
    (tmp_path / "claude-foothold-homelab.service").write_text("old")
    _sync(tmp_path, ("main",), run=_recording_run(returncode=1, fail_on="systemctl")[0])
    assert "claude-foothold-homelab.service" in _units(tmp_path)


def test_sync_keeps_the_legacy_unit_when_a_burst_only_preset_cannot_start_burst(tmp_path):
    (tmp_path / "claude-foothold-homelab.service").write_text("old")
    _sync(tmp_path, ("burst",))
    assert _units(tmp_path) == ["claude-foothold-homelab.service"]


def test_sync_retires_the_legacy_unit_once_a_burst_only_preset_starts_burst(tmp_path):
    (tmp_path / "claude-foothold-homelab.service").write_text("old")
    _sync(tmp_path, ("burst",), burst_dir=_logged_in_burst(tmp_path))
    assert _units(tmp_path) == ["claude-foothold-burst.service"]


def test_a_legacy_unit_left_by_a_failed_install_is_retired_on_a_later_one(tmp_path):
    (tmp_path / "claude-foothold-oldpreset.service").write_text("old")
    _sync(tmp_path, ("burst",))
    assert "claude-foothold-oldpreset.service" in _units(tmp_path)
    _sync(tmp_path, ("burst",), burst_dir=_logged_in_burst(tmp_path))
    assert _units(tmp_path) == ["claude-foothold-burst.service"]


def test_sync_warns_about_an_unknown_account(tmp_path, capsys):
    _sync(tmp_path, ("main", "spare"))
    assert "Unknown foothold account 'spare'" in capsys.readouterr().out


def test_restart_footholds_restarts_every_installed_unit(tmp_path):
    _installed_unit(tmp_path, "main")
    _installed_unit(tmp_path, "burst")
    run, calls = _recording_run()
    assert foothold.restart_footholds(Logger(dry_run=False), unit_dir=tmp_path, run=run) is True
    # One call, so a restart issued from inside the main session still reaches the burst unit.
    assert calls == [PROBE, RELOAD, (*RESTART, "claude-foothold-burst.service")]


def test_restart_footholds_fails_when_none_is_installed(tmp_path, capsys):
    run, calls = _recording_run()
    assert foothold.restart_footholds(Logger(dry_run=False), unit_dir=tmp_path, run=run) is False
    assert calls == []
    assert "No foothold is installed" in capsys.readouterr().out


def test_dry_run_changes_nothing(tmp_path, capsys):
    run, calls = _recording_run()
    _install(tmp_path, dry_run=True, run=run)
    assert calls == []
    assert list(tmp_path.iterdir()) == []
    assert "claude-foothold.service" in capsys.readouterr().out


@pytest.mark.parametrize("tool", foothold.REQUIRED_TOOLS)
def test_a_missing_required_tool_warns_and_skips(tmp_path, monkeypatch, capsys, tool):
    monkeypatch.setattr("dotfiles_setup.foothold.shutil.which", lambda name: None if name == tool else "/bin/x")
    run, calls = _recording_run()
    _install(tmp_path, run=run)
    assert calls == []
    assert list(tmp_path.iterdir()) == []
    assert f"{tool} not found" in capsys.readouterr().out


def test_a_failing_command_warns_without_raising(tmp_path, capsys):
    _install(tmp_path, run=_recording_run(returncode=1, stderr="no bus")[0])
    assert "no bus" in capsys.readouterr().out


def test_install_reports_success(tmp_path):
    assert _install(tmp_path) is True


def test_install_reports_failure_when_a_command_fails(tmp_path):
    assert _install(tmp_path, run=_recording_run(returncode=1)[0]) is False


def test_install_reports_failure_when_a_tool_is_missing(tmp_path, monkeypatch):
    monkeypatch.setattr("dotfiles_setup.foothold.shutil.which", lambda name: None)
    assert _install(tmp_path) is False


def test_an_unwritable_unit_dir_warns_without_raising(tmp_path, capsys):
    blocker = tmp_path / "file"
    blocker.write_text("")
    _install(blocker)
    assert "Could not set up claude-foothold.service" in capsys.readouterr().out
