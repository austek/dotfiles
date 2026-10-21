"""Boot-time Claude Code Remote Control session for the machine's preset, run as a tmux-hosted systemd user unit."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from dotfiles_setup.log import Logger

UNIT_DIR = Path.home() / ".config" / "systemd" / "user"
REQUIRED_TOOLS = ("systemctl", "tmux", "curl")
NETWORK_PROBE_URL = "https://api.anthropic.com"
PATH_DIRS = (
    "%h/.local/share/sonarqube-cli/bin",
    "%h/.local/bin",
    "%h/.dotfiles/bin",
    "%h/.sdkman/candidates/java/current/bin",
    "/usr/local/bin",
    "/usr/bin",
    "/bin",
)


def foothold_name(preset_name: str) -> str:
    return f"foothold-{preset_name}"


def session_name(preset_name: str) -> str:
    return f"claude-{foothold_name(preset_name)}"


def unit_name(preset_name: str) -> str:
    return f"{session_name(preset_name)}.service"


def unit_path_for(path: Path, home: Path) -> str:
    """Returns path as `%h/<relative>` when under home, else the absolute path."""
    return f"%h/{path.relative_to(home)}" if path.is_relative_to(home) else str(path)


def _launch_command(preset_name: str, settings: str) -> str:
    tmux = session_name(preset_name)
    return (
        f'tmux has-session -t {tmux} 2>/dev/null || exec tmux new-session -d -s {tmux} -c "%h/Workspace" '
        f'claude --remote-control {foothold_name(preset_name)} --settings "{settings}"'
    )


def _service_section(preset_name: str, settings: str) -> tuple[str, ...]:
    return (
        "[Service]",
        "Type=oneshot",
        "RemainAfterExit=yes",
        "KillMode=process",
        "TimeoutStartSec=180",
        "Restart=on-failure",
        "RestartSec=30",
        f'Environment="PATH={":".join(PATH_DIRS)}"',
        # The link gains carrier before DNS and routes work; Remote Control fails session creation if it starts earlier.
        f"ExecStartPre=/usr/bin/env curl -s --retry 30 --retry-delay 2 --retry-all-errors --max-time 5 -o /dev/null {NETWORK_PROBE_URL}",
        f"ExecStart=/bin/sh -c '{_launch_command(preset_name, settings)}'",
    )


def render_unit(preset_name: str, settings: str) -> str:
    unit_section = (
        "[Unit]",
        f"Description=Claude remote-control session {foothold_name(preset_name)}",
        "After=network-online.target",
        "Wants=network-online.target",
    )
    install_section = ("[Install]", "WantedBy=default.target")
    sections = (unit_section, _service_section(preset_name, settings), install_section)
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


def retire_foothold(
    logger: Logger, preset_name: str, unit_dir: Path = UNIT_DIR, run=subprocess.run,
) -> None:
    """Disables a replaced preset's unit, ends its tmux session and removes its unit file. No-op without that unit."""
    unit = unit_dir / unit_name(preset_name)
    if not unit.is_file() or logger.dry_run_notice(f"Would retire {unit.name} and its tmux session."):
        return
    try:
        _run_command(("systemctl", "--user", "disable", "--now", unit.name), logger, run)
        run(("tmux", "kill-session", "-t", session_name(preset_name)), capture_output=True, stdin=subprocess.DEVNULL)
        unit.unlink()
        _run_command(("systemctl", "--user", "daemon-reload"), logger, run)
    except OSError as exc:
        logger.warn(f"Could not retire {foothold_name(preset_name)}: {exc}")
        return
    logger.info(f"Retired {unit.name}.")


def install_foothold(
    logger: Logger, preset_name: str, profile_path: Path | None,
    unit_dir: Path = UNIT_DIR, home: Path | None = None, run=subprocess.run,
) -> bool:
    """Installs and enables the per-preset unit and lingering. Returns whether it succeeded or had nothing to do; warns instead of raising."""
    if profile_path is None:
        return True
    unit = unit_dir / unit_name(preset_name)
    if logger.dry_run_notice(f"Would install {unit}, enable linger and start {unit.name}."):
        return True
    if missing := _missing_tools():
        logger.warn(f"{', '.join(missing)} not found; skipping {foothold_name(preset_name)} setup.")
        return False
    settings = unit_path_for(profile_path, home or Path.home())
    try:
        _write_unit(unit, render_unit(preset_name, settings))
        results = [_run_command(argv, logger, run) for argv in _commands(unit.name)]
    except OSError as exc:
        logger.warn(f"Could not set up {foothold_name(preset_name)}: {exc}")
        return False
    if all(results):
        logger.info(f"Installed {unit.name}; attach with `tmux attach -t {session_name(preset_name)}`.")
    return all(results)
