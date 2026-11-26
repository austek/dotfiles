"""The doctor's checks, in the order they run."""
from __future__ import annotations

import json
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from dotfiles_setup.findings import CheckOutcome, Finding
from dotfiles_setup.tooling import COMMAND_NOT_FOUND, Tooling


@dataclass(frozen=True)
class CheckContext:
    t: Tooling
    packages: tuple[str, ...] | None


Check = Callable[[CheckContext], CheckOutcome]

PLUGIN_CHECK = "plugin_load_errors"


def _plugin_finding(plugin: dict[str, Any]) -> Finding:
    plugin_id, scope = plugin["id"], plugin.get("scope", "user")
    claude = ("claude", "plugin")
    return Finding(
        PLUGIN_CHECK,
        f"{plugin_id} has load errors: {'; '.join(plugin['errors'])}",
        affects=(plugin_id,),
        commands=(
            (*claude, "uninstall", plugin_id, "--scope", scope),
            (*claude, "install", plugin_id, "--scope", scope),
        ),
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


CHECKS: dict[str, Check] = {
    "stale_copies": lambda ctx: CheckOutcome(),
    PLUGIN_CHECK: check_plugin_load_errors,
}
