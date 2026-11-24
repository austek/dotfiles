"""The read-only plan an apply prints before it changes anything."""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from dotfiles_setup.log import Logger

UNKNOWN_NOTE = "checked during apply"
UPGRADE_NOTE = "from local apt cache"
HELD_NOTE = "pass --prune to remove"


@dataclass(frozen=True)
class StepPlan:
    step: str
    wanted: int
    installed: int
    install: tuple[str, ...] = ()
    remove: tuple[str, ...] = ()
    upgrade: tuple[str, ...] = ()
    held: tuple[str, ...] = ()
    note: str | None = None
    known: bool = True
    change: tuple[str, ...] = ()
    needs_sudo: bool = False
    reason: str | None = None


def unknown_step(step: str, note: str | None = None) -> StepPlan:
    return StepPlan(step, 0, 0, note=note, known=False)


def row(plans: Sequence[StepPlan], step: str) -> StepPlan | None:
    return next((plan for plan in plans if plan.step == step), None)


def has_changes(plan: StepPlan) -> bool:
    return plan.known and bool(plan.install or plan.remove or plan.upgrade or plan.change)


def is_empty(plans: Sequence[StepPlan]) -> bool:
    return not any(has_changes(plan) for plan in plans)


def _names(label: str, names: tuple[str, ...], suffix: str = "") -> list[str]:
    return [f"    {label}{suffix}: {', '.join(names)}"] if names else []


def _known_lines(plan: StepPlan) -> list[str]:
    counts = f"{plan.wanted} wanted, {plan.installed} installed" if plan.wanted else ""
    head = f"  {plan.step}: {counts}" if counts else f"  {plan.step}:"
    return [
        head,
        *_names("to install", plan.install),
        *_names("to change", plan.change),
        *_names("to remove", plan.remove),
        *_names("held back", plan.held, f" ({HELD_NOTE})"),
        *_names("to upgrade", plan.upgrade, f" ({UPGRADE_NOTE})"),
        *([f"    note: {plan.note}"] if plan.note else []),
    ]


def _unknown_lines(plan: StepPlan) -> list[str]:
    return [f"  {plan.step}: {UNKNOWN_NOTE}" + (f" ({plan.note})" if plan.note else "")]


def _has_content(plan: StepPlan) -> bool:
    return bool(plan.wanted or plan.install or plan.remove or plan.held or plan.upgrade or plan.change or plan.note)


def _lines(plan: StepPlan) -> list[str]:
    if not plan.known:
        return _unknown_lines(plan)
    return _known_lines(plan) if _has_content(plan) else []


def render_plan(logger: Logger, plans: Sequence[StepPlan]) -> None:
    logger.step("Plan")
    for plan in plans:
        for line in _lines(plan):
            logger.say(line)
    unknown = [plan.step for plan in plans if not plan.known]
    if unknown:
        logger.say(f"Also runs: {', '.join(unknown)}")
