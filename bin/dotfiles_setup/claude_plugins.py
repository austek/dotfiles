"""Refreshes Claude Code marketplaces and user-scope plugins after an install."""
from __future__ import annotations

import json
import subprocess

from dotfiles_setup.log import Logger


def _claude(*args: str, run=subprocess.run) -> subprocess.CompletedProcess:
    return run(["claude", "plugin", *args], capture_output=True, text=True, stdin=subprocess.DEVNULL)


def _installed_user_plugins(run) -> tuple[str, ...]:
    listed = _claude("list", "--json", run=run)
    if listed.returncode != 0:
        return ()
    entries = json.loads(listed.stdout or "[]")
    return tuple(dict.fromkeys(e["id"] for e in entries if e.get("scope") == "user"))


def _update_plugin(plugin_id: str, logger: Logger, run) -> None:
    result = _claude("update", plugin_id, "--scope", "user", run=run)
    if result.returncode != 0:
        logger.warn(f"Could not update {plugin_id}: {result.stderr.strip() or result.stdout.strip()}")


def update_claude_plugins(logger: Logger, run=subprocess.run) -> None:
    """Updates every marketplace, then each user-scope plugin. Never fails the install."""
    if logger.dry_run_notice("Would update Claude Code marketplaces and plugins."):
        return
    try:
        refreshed = _claude("marketplace", "update", run=run)
        plugins = _installed_user_plugins(run)
    except FileNotFoundError:
        logger.warn("claude is not installed; skipping plugin update.")
        return
    if refreshed.returncode != 0:
        logger.warn(f"Could not refresh marketplaces: {refreshed.stderr.strip()}")
    for plugin_id in plugins:
        _update_plugin(plugin_id, logger, run)
    logger.info(f"Checked {len(plugins)} Claude Code plugin(s) for updates (restart Claude Code to apply).")
