"""Boot-time Claude Code Remote Control sessions, one per account, each run as a tmux-hosted systemd user unit.

The main account's session is named after the machine's hostname and the burst account's (see bin/claude-burst-link)
after the hostname plus `-burst`. Which accounts get one is the preset's `footholds` list.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from dotfiles_setup.log import Logger

UNIT_DIR = Path.home() / ".config" / "systemd" / "user"
BURST_DIR = Path.home() / ".claude-burst"
ACCOUNTS = ("main", "burst")
REQUIRED_TOOLS = ("systemctl", "tmux", "curl")
NETWORK_PROBE_URL = "https://api.anthropic.com"
LAUNCHER = "%h/.dotfiles/bin/claude-foothold-launch"
PATH_DIRS = (
    "%h/.local/share/sonarqube-cli/bin",
    "%h/.local/bin",
    "%h/.dotfiles/bin",
    "%h/.sdkman/candidates/java/current/bin",
    "/usr/local/bin",
    "/usr/bin",
    "/bin",
)


def session_name(account: str) -> str:
    return "claude-foothold" if account == "main" else f"claude-foothold-{account}"


def unit_name(account: str) -> str:
    return f"{session_name(account)}.service"


def remote_control_name(account: str) -> str:
    """systemd expands %H to the hostname when the unit starts, so a renamed machine needs no rewrite."""
    return "%H" if account == "main" else f"%H-{account}"


def _legacy_unit_name(preset_name: str) -> str:
    """Units were named after the preset before they were named after the hostname."""
    return f"claude-foothold-{preset_name}.service"


def _launch_command(account: str) -> str:
    tmux = session_name(account)
    launch = f"{LAUNCHER} {remote_control_name(account)}"
    if account != "main":
        launch += f" {account}"
    return f'tmux has-session -t ={tmux} 2>/dev/null || exec tmux new-session -d -s {tmux} -c "%h/Workspace" {launch}'


def _service_section(account: str) -> tuple[str, ...]:
    return (
        "[Service]",
        "Type=oneshot",
        "RemainAfterExit=yes",
        "KillMode=process",
        "TimeoutStartSec=300",
        "Restart=on-failure",
        "RestartSec=30",
        f'Environment="PATH={":".join(PATH_DIRS)}"',
        # Headless sessions never source ~/.zshrc, which is where these vars otherwise come from.
        "EnvironmentFile=-%h/.config/dotfiles/secrets.env",
        # The link gains carrier before DNS and routes work; Remote Control fails session creation if it starts earlier.
        f"ExecStartPre=/usr/bin/env curl -s --retry 30 --retry-delay 2 --retry-all-errors --max-time 5 -o /dev/null {NETWORK_PROBE_URL}",
        f"ExecStart=/bin/sh -c '{_launch_command(account)}'",
        # Runs only on stop or restart, never on a plain start. Under systemd, not in the pane, so a restart issued
        # from inside the session still completes.
        f"ExecStop=-/usr/bin/env tmux kill-session -t ={session_name(account)}",
    )


def render_unit(account: str) -> str:
    unit_section = (
        "[Unit]",
        f"Description=Claude remote-control session {remote_control_name(account)}",
        "After=network-online.target",
        "Wants=network-online.target",
    )
    install_section = ("[Install]", "WantedBy=default.target")
    sections = (unit_section, _service_section(account), install_section)
    return "\n\n".join("\n".join(section) for section in sections) + "\n"


def _commands(unit: str) -> tuple[tuple[str, ...], ...]:
    return (
        ("loginctl", "enable-linger"),
        ("systemctl", "--user", "daemon-reload"),
        ("systemctl", "--user", "enable", "--now", unit),
    )


def _write_unit(unit: Path, rendered: str) -> None:
    unit.parent.mkdir(parents=True, exist_ok=True)
    if not (unit.is_file() and unit.read_text(encoding="utf-8") == rendered):
        unit.write_text(rendered, encoding="utf-8")


def _run_command(argv: tuple[str, ...], logger: Logger, run) -> bool:
    result = run(argv, capture_output=True, text=True, stdin=subprocess.DEVNULL)
    if result.returncode != 0:
        logger.warn(f"`{' '.join(argv)}` failed: {result.stderr.strip() or result.stdout.strip()}")
    return result.returncode == 0


def _missing_tools() -> tuple[str, ...]:
    return tuple(tool for tool in REQUIRED_TOOLS if shutil.which(tool) is None)


def _retire_unit(logger: Logger, unit: Path, session: str, run) -> None:
    if not unit.is_file() or logger.dry_run_notice(f"Would retire {unit.name} and its tmux session."):
        return
    try:
        _run_command(("systemctl", "--user", "disable", "--now", unit.name), logger, run)
        run(("tmux", "kill-session", "-t", f"={session}"), capture_output=True, stdin=subprocess.DEVNULL)
        unit.unlink()
        _run_command(("systemctl", "--user", "daemon-reload"), logger, run)
    except OSError as exc:
        logger.warn(f"Could not retire {unit.name}: {exc}")
        return
    logger.info(f"Retired {unit.name}.")


def retire_foothold(logger: Logger, account: str, unit_dir: Path = UNIT_DIR, run=subprocess.run) -> None:
    """Disables an account's unit, ends its tmux session and removes its unit file. No-op without that unit."""
    _retire_unit(logger, unit_dir / unit_name(account), session_name(account), run)


def retire_legacy_foothold(logger: Logger, preset_name: str, unit_dir: Path = UNIT_DIR, run=subprocess.run) -> None:
    """Retires the preset-named unit an older install wrote. No-op without that unit."""
    if preset_name in ACCOUNTS:
        return
    unit = unit_dir / _legacy_unit_name(preset_name)
    _retire_unit(logger, unit, unit.name.removesuffix(".service"), run)


def _rewrite_if_stale(unit: Path, account: str, logger: Logger) -> None:
    rendered = render_unit(account)
    if unit.read_text(encoding="utf-8") != rendered:
        _write_unit(unit, rendered)
        logger.info(f"Rewrote stale {unit.name}.")


def _network_up(logger: Logger, run) -> bool:
    probe = ("curl", "-s", "--max-time", "5", "-o", "/dev/null", NETWORK_PROBE_URL)
    return _run_command(probe, logger, run)


def _reload_and_restart(unit: Path, account: str, logger: Logger, run) -> bool:
    _rewrite_if_stale(unit, account, logger)
    commands = (("systemctl", "--user", "daemon-reload"), ("systemctl", "--user", "restart", unit.name))
    return all(_run_command(argv, logger, run) for argv in commands)


def restart_foothold(logger: Logger, account: str, unit_dir: Path = UNIT_DIR, run=subprocess.run) -> bool:
    """Restarts an account's unit in a fresh tmux session. Safe to call from inside the foothold session.

    Returns False when the unit is missing or the restart fails; warns instead of raising.
    """
    unit = unit_dir / unit_name(account)
    if not unit.is_file():
        logger.warn(f"{unit.name} is not installed; run `dotfiles-setup install` first.")
        return False
    if logger.dry_run_notice(f"Would rewrite {unit.name} if stale, then restart it."):
        return True
    try:
        restarted = _network_up(logger, run) and _reload_and_restart(unit, account, logger, run)
    except OSError as exc:
        logger.warn(f"Could not restart {unit.name}: {exc}")
        return False
    if restarted:
        logger.info(f"Restarted {unit.name}; attach with `tmux attach -t {session_name(account)}`.")
    return restarted


def restart_footholds(logger: Logger, unit_dir: Path = UNIT_DIR, run=subprocess.run) -> bool:
    """Restarts every installed account unit. Returns False when none is installed or any restart fails."""
    installed = [account for account in ACCOUNTS if (unit_dir / unit_name(account)).is_file()]
    if not installed:
        logger.warn("No foothold is installed; run `dotfiles-setup install` on a preset that enables one.")
        return False
    results = [restart_foothold(logger, account, unit_dir, run) for account in installed]
    return all(results)


def install_foothold(
    logger: Logger, account: str, unit_dir: Path = UNIT_DIR, run=subprocess.run, burst_dir: Path = BURST_DIR,
) -> bool:
    """Installs and enables an account's unit and lingering. Returns whether it succeeded; warns instead of raising.

    The burst unit waits for the burst account's first login, since Remote Control cannot start without one.
    """
    unit = unit_dir / unit_name(account)
    if account == "burst" and not (burst_dir / ".credentials.json").is_file():
        logger.warn(f"Skipping {unit.name}: log in once with `claude-burst` then /login, and re-run the install.")
        return False
    if logger.dry_run_notice(f"Would install {unit}, enable linger and start {unit.name}."):
        return True
    if missing := _missing_tools():
        logger.warn(f"{', '.join(missing)} not found; skipping {unit.name}.")
        return False
    try:
        _write_unit(unit, render_unit(account))
        results = [_run_command(argv, logger, run) for argv in _commands(unit.name)]
    except OSError as exc:
        logger.warn(f"Could not set up {unit.name}: {exc}")
        return False
    if all(results):
        logger.info(f"Installed {unit.name}; attach with `tmux attach -t {session_name(account)}`.")
    return all(results)


def sync_footholds(
    logger: Logger, wanted: tuple[str, ...], legacy_presets: tuple[str, ...],
    unit_dir: Path = UNIT_DIR, run=subprocess.run, burst_dir: Path = BURST_DIR,
) -> None:
    """Installs the wanted accounts' units and retires the rest, plus any preset-named unit an older install wrote.

    The legacy units are retired only once the main account's replacement is up, or when the preset wants none.
    """
    for unknown in sorted(set(wanted) - set(ACCOUNTS)):
        logger.warn(f"Unknown foothold account '{unknown}'; expected one of {', '.join(ACCOUNTS)}.")
    main_ok = True
    for account in ACCOUNTS:
        if account not in wanted:
            retire_foothold(logger, account, unit_dir, run)
            continue
        installed = install_foothold(logger, account, unit_dir, run, burst_dir)
        if account == "main":
            main_ok = installed
    if main_ok:
        for preset_name in dict.fromkeys(legacy_presets):
            retire_legacy_foothold(logger, preset_name, unit_dir, run)
