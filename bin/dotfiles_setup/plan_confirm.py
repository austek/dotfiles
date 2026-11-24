"""Shows the plan and decides whether the apply goes on."""
from __future__ import annotations

from collections.abc import Callable, Sequence

from dotfiles_setup.log import Logger
from dotfiles_setup.plan_types import StepPlan, is_empty, render_plan

NEEDS_YES_EXIT_CODE = 5
DECLINED_EXIT_CODE = 6
PROMPT = "Continue? [y/N] "


def _answered_yes(logger: Logger, ask: Callable[[str], str]) -> bool:
    try:
        return ask(PROMPT).strip().lower() in ("y", "yes")
    except EOFError:
        logger.say("")
        return False


def confirm_plan(
    logger: Logger, plans: Sequence[StepPlan], *, yes: bool, interactive: bool, dry_run: bool,
    ask: Callable[[str], str] = input,
) -> int | None:
    """None when the apply should go on, else the exit code to stop with."""
    render_plan(logger, plans)
    if dry_run or yes or is_empty(plans):
        return None
    if not interactive:
        logger.warn("The plan changes this machine; pass --yes to apply.")
        return NEEDS_YES_EXIT_CODE
    if _answered_yes(logger, ask):
        return None
    logger.warn("Declined; no install step ran.")
    return DECLINED_EXIT_CODE
