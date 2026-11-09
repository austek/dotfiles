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


def _legacy_units(unit_dir: Path) -> list[Path]:
    """Units were named after the preset (claude-foothold-<preset>.service) before they were named after the hostname."""
    current = {unit_name(account) for account in ACCOUNTS}
    return sorted(u for u in unit_dir.glob("claude-foothold-*.service") if u.name not in current)


def _launch_command(account: str) -> str:
    command = f"{LAUNCHER} --start {session_name(account)} %h/Workspace {remote_control_name(account)}"
    return command if account == "main" else f"{command} {account}"


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
        # The link gains carrier before DNS and routes work; Remote Control fails session creation if it starts earlier.
        f"ExecStartPre=/usr/bin/env curl -s --retry 30 --retry-delay 2 --retry-all-errors --max-time 5 -o /dev/null {NETWORK_PROBE_URL}",
        f"ExecStart={_launch_command(account)}",
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


def retire_legacy_footholds(logger: Logger, unit_dir: Path = UNIT_DIR, run=subprocess.run) -> None:
    """Retires every preset-named unit an older install wrote, whichever preset it was for."""
    for unit in _legacy_units(unit_dir):
        _retire_unit(logger, unit, unit.name.removesuffix(".service"), run)


def _rewrite_if_stale(unit: Path, account: str, logger: Logger) -> None:
    rendered = render_unit(account)
    if unit.read_text(encoding="utf-8") != rendered:
        _write_unit(unit, rendered)
        logger.info(f"Rewrote stale {unit.name}.")


def _network_up(logger: Logger, run) -> bool:
    probe = ("curl", "-s", "--max-time", "5", "-o", "/dev/null", NETWORK_PROBE_URL)
    return _run_command(probe, logger, run)


def _reload_and_restart(units: list[tuple[Path, str]], logger: Logger, run) -> bool:
    for unit, account in units:
        _rewrite_if_stale(unit, account, logger)
    # systemctl asks for each unit's restart in turn, and ending a foothold session kills a caller running in it
    # before it asks for the next. A transient unit outside every session issues them all; --wait keeps the result.
    restart = (
        "systemd-run", "--user", "--wait", "--collect", "--quiet", "--",
        "systemctl", "--user", "restart", *(unit.name for unit, _ in units),
    )
    commands = (("systemctl", "--user", "daemon-reload"), restart)
    return all(_run_command(argv, logger, run) for argv in commands)


def _restart_units(logger: Logger, accounts: list[str], unit_dir: Path, run) -> bool:
    units = [(unit_dir / unit_name(account), account) for account in accounts]
    names = ", ".join(unit.name for unit, _ in units)
    if logger.dry_run_notice(f"Would rewrite {names} if stale, then restart them."):
        return True
    try:
        restarted = _network_up(logger, run) and _reload_and_restart(units, logger, run)
    except OSError as exc:
        logger.warn(f"Could not restart {names}: {exc}")
        return False
    if restarted:
        sessions = " or ".join(f"`tmux attach -t {session_name(account)}`" for account in accounts)
        logger.info(f"Restarted {names}; attach with {sessions}.")
    return restarted


def restart_foothold(logger: Logger, account: str, unit_dir: Path = UNIT_DIR, run=subprocess.run) -> bool:
    """Restarts an account's unit in a fresh tmux session. Safe to call from inside the foothold session.

    Returns False when the unit is missing or the restart fails; warns instead of raising.
    """
    unit = unit_dir / unit_name(account)
    if not unit.is_file():
        logger.warn(f"{unit.name} is not installed; run `dotfiles-setup install` first.")
        return False
    return _restart_units(logger, [account], unit_dir, run)


def restart_footholds(logger: Logger, unit_dir: Path = UNIT_DIR, run=subprocess.run) -> bool:
    """Restarts every installed account unit together. Returns False when none is installed or the restart fails."""
    installed = [account for account in ACCOUNTS if (unit_dir / unit_name(account)).is_file()]
    if not installed:
        logger.warn("No foothold is installed; run `dotfiles-setup install` on a preset that enables one.")
        return False
    return _restart_units(logger, installed, unit_dir, run)


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
    logger: Logger, wanted: tuple[str, ...], unit_dir: Path = UNIT_DIR, run=subprocess.run, burst_dir: Path = BURST_DIR,
) -> None:
    """Installs the wanted accounts' units and retires the rest, plus any preset-named unit an older install wrote.

    A legacy unit ran the main account, so it is retired once the main unit is up, or, for a preset without
    main, once every wanted unit is up (with none wanted, at once). Otherwise it keeps running until a later install
    finds it again by name.
    """
    for unknown in sorted(set(wanted) - set(ACCOUNTS)):
        logger.warn(f"Unknown foothold account '{unknown}'; expected one of {', '.join(ACCOUNTS)}.")
    installed: dict[str, bool] = {}
    for account in ACCOUNTS:
        if account in wanted:
            installed[account] = install_foothold(logger, account, unit_dir, run, burst_dir)
        else:
            retire_foothold(logger, account, unit_dir, run)
    if installed["main"] if "main" in installed else all(installed.values()):
        retire_legacy_footholds(logger, unit_dir, run)
