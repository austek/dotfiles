"""Reconciles Claude Code marketplaces and user-scope plugins with the generated settings after an install."""
from __future__ import annotations

import json
import subprocess
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from dotfiles_setup.log import Logger

LEGACY_MARKETPLACES = frozenset({"claude-skills"})
UPDATE_WORKERS = 4


@dataclass(frozen=True)
class Action:
    label: str
    args: tuple[str, ...]


def _claude(*args: str, run=subprocess.run) -> subprocess.CompletedProcess:
    return run(["claude", "plugin", *args], capture_output=True, text=True, stdin=subprocess.DEVNULL)


def _list_json(run, *args: str) -> list[dict] | None:
    listed = _claude(*args, "--json", run=run)
    return json.loads(listed.stdout or "[]") if listed.returncode == 0 else None


def _marketplace_source(declared: dict) -> str | None:
    source = declared.get("source", {})
    return {"github": source.get("repo"), "git": source.get("url")}.get(source.get("source"))


def _enabled_plugins(settings: dict) -> tuple[str, ...]:
    return tuple(sorted(pid for pid, on in settings.get("enabledPlugins", {}).items() if on))


def _declared_marketplaces(settings: dict) -> frozenset[str]:
    return frozenset(settings.get("extraKnownMarketplaces", {}))


def _managed_marketplaces(settings: dict) -> frozenset[str]:
    return _declared_marketplaces(settings) | LEGACY_MARKETPLACES


def _marketplace_adds(settings: dict, registered: frozenset[str]) -> tuple[Action, ...]:
    declared = settings.get("extraKnownMarketplaces", {})
    return tuple(
        Action(f"add marketplace {name}", ("marketplace", "add", source))
        for name, source in ((n, _marketplace_source(d)) for n, d in declared.items())
        if source and name not in registered
    )


def _plugin_installs(settings: dict, installed: tuple[str, ...]) -> tuple[Action, ...]:
    return tuple(
        Action(f"install {p}", ("install", p, "--scope", "user"))
        for p in _enabled_plugins(settings) if p not in installed
    )


def _plugin_removals(settings: dict, installed: tuple[str, ...]) -> tuple[Action, ...]:
    enabled, managed = _enabled_plugins(settings), _managed_marketplaces(settings)
    stale = [p for p in installed if p not in enabled and p.partition("@")[2] in managed]
    return tuple(Action(f"uninstall {p}", ("uninstall", p, "--scope", "user")) for p in stale) if enabled else ()


def _marketplace_removals(settings: dict, registered: frozenset[str]) -> tuple[Action, ...]:
    if not _enabled_plugins(settings):
        return ()
    stale = sorted((registered & LEGACY_MARKETPLACES) - _declared_marketplaces(settings))
    return tuple(Action(f"remove marketplace {n}", ("marketplace", "remove", n)) for n in stale)


def _updates(settings: dict, installed: tuple[str, ...]) -> tuple[Action, ...]:
    gone = {a.args[1] for a in _plugin_removals(settings, installed)}
    return tuple(Action(f"update {p}", ("update", p, "--scope", "user")) for p in installed if p not in gone)


def plan_actions(settings: dict, registered: frozenset[str], installed: tuple[str, ...]) -> tuple[Action, ...]:
    """Ordered actions that sync Claude Code with settings; uninstalls and marketplace adds/removes cover only managed marketplaces.

    Legacy marketplaces go before adds because a renamed marketplace collides with its old name.
    """
    return (
        *_plugin_removals(settings, installed),
        *_marketplace_removals(settings, registered),
        *_marketplace_adds(settings, registered),
        Action("refresh marketplaces", ("marketplace", "update")),
        *_plugin_installs(settings, installed),
        *_updates(settings, installed),
    )


def _snapshot(run) -> tuple[frozenset[str], tuple[str, ...]] | None:
    marketplaces, plugins = _list_json(run, "marketplace", "list"), _list_json(run, "list")
    if marketplaces is None or plugins is None:
        return None
    user_ids = dict.fromkeys(e["id"] for e in plugins if e.get("scope") == "user")
    return frozenset(m["name"] for m in marketplaces), tuple(user_ids)


def _apply(action: Action, logger: Logger, run) -> None:
    if logger.dry_run_notice(f"Would {action.label}."):
        return
    logger.info(f"Running: {action.label}")
    try:
        result = _claude(*action.args, run=run)
    except OSError as exc:
        logger.warn(f"Could not {action.label}: {exc}")
        return
    if result.returncode != 0:
        logger.warn(f"Could not {action.label}: {result.stderr.strip() or result.stdout.strip()}")


def _apply_all(actions: tuple[Action, ...], logger: Logger, run) -> None:
    updates = [a for a in actions if a.args[0] == "update"]
    for action in (a for a in actions if a not in updates):
        _apply(action, logger, run)
    workers = 1 if logger.dry_run else UPDATE_WORKERS
    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(lambda a: _apply(a, logger, run), updates))


def update_claude_plugins(logger: Logger, settings: dict, run=subprocess.run) -> None:
    """Applies (or, in a dry run, prints) the plan that syncs Claude Code with settings. Warns instead of raising."""
    try:
        snapshot = _snapshot(run)
        if snapshot is None:
            logger.warn("Could not list Claude Code plugins; skipping plugin sync.")
            return
        actions = plan_actions(settings, *snapshot)
        _apply_all(actions, logger, run)
    except FileNotFoundError:
        logger.warn("claude is not installed; skipping plugin sync.")
        return
    except (json.JSONDecodeError, KeyError) as exc:
        logger.warn(f"Unexpected `claude plugin` output ({exc!r}); skipping plugin sync.")
        return
    verb = "Planned" if logger.dry_run else "Attempted"
    logger.info(f"{verb} {len(actions)} Claude Code plugin action(s); restart Claude Code to apply.")
