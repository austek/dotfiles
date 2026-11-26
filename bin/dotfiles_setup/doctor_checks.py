"""The doctor's checks, in the order they run."""
from __future__ import annotations

import json
import os
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dotfiles_setup import stale_copies
from dotfiles_setup.findings import CheckOutcome, Finding
from dotfiles_setup.tooling import COMMAND_NOT_FOUND, Tooling


@dataclass(frozen=True)
class CheckContext:
    t: Tooling
    packages: tuple[str, ...] | None


Check = Callable[[CheckContext], CheckOutcome]

PLUGIN_CHECK = "plugin_load_errors"
STALE_COPIES_CHECK = "stale_copies"


def _project_plugin_finding(plugin_id: str, scope: str, project: str | None, errors: str) -> Finding:
    reinstall = f"claude plugin uninstall {plugin_id} --scope {scope}, then claude plugin install {plugin_id} --scope {scope}"
    return Finding(
        PLUGIN_CHECK,
        f"{plugin_id} ({scope} scope, {project or 'an unknown project'}) has load errors: {errors}",
        affects=(plugin_id, project) if project else (plugin_id,),
        advice=f"In {project or 'the project that owns it'}: {reinstall}.",
    )


def _plugin_finding(plugin: dict[str, Any]) -> Finding:
    plugin_id, scope, errors = plugin["id"], plugin.get("scope", "user"), "; ".join(plugin["errors"])
    if scope != "user":
        return _project_plugin_finding(plugin_id, scope, plugin.get("projectPath"), errors)
    claude = ("claude", "plugin")
    return Finding(
        PLUGIN_CHECK,
        f"{plugin_id} has load errors: {errors}",
        affects=(plugin_id,),
        commands=((*claude, "uninstall", plugin_id, "--scope", scope), (*claude, "install", plugin_id, "--scope", scope)),
    )


def _list_failed(reason: str) -> CheckOutcome:
    return CheckOutcome((Finding(
        PLUGIN_CHECK,
        f"`claude plugin list` failed: {reason}",
        advice="Run `claude plugin list` by hand to see why.",
    ),))


def check_plugin_load_errors(ctx: CheckContext) -> CheckOutcome:
    result = ctx.t.run(
        ["claude", "plugin", "list", "--json"], capture_output=True, text=True, stdin=subprocess.DEVNULL
    )
    if result.returncode == COMMAND_NOT_FOUND:
        return CheckOutcome(skipped="claude is not installed")
    if result.returncode != 0:
        return _list_failed(result.stderr.strip() or result.stdout.strip())
    try:
        plugins = json.loads(result.stdout or "[]")
    except json.JSONDecodeError as error:
        return _list_failed(f"unparsable output ({error})")
    return CheckOutcome(tuple(_plugin_finding(p) for p in plugins if p.get("errors")))


def _shadow_finding(copy: Path, managed: Path) -> Finding:
    root_note = "" if os.access(copy.parent, os.W_OK) else f" (as root: {copy.parent} is not writable)"
    return Finding(
        STALE_COPIES_CHECK,
        f"{copy} precedes {managed} on PATH and shadows it.",
        affects=(str(copy),),
        advice=f"rm {copy}{root_note}",
    )


def check_stale_copies(ctx: CheckContext) -> CheckOutcome:
    if ctx.packages is None:
        return CheckOutcome(skipped="no saved preset on this machine")
    names = stale_copies.managed_names(ctx.packages)
    return CheckOutcome(tuple(_shadow_finding(c, m) for c, m in stale_copies.shadowing_copies(ctx.t, names)))


CHECKS: dict[str, Check] = {
    STALE_COPIES_CHECK: check_stale_copies,
    PLUGIN_CHECK: check_plugin_load_errors,
}
