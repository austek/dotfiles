"""Asks whether the packages an install no longer wants should be removed."""
from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Sequence

from dotfiles_setup import flatpak, removals, tooling
from dotfiles_setup.log import Logger
from dotfiles_setup.plan import _Install


def _uninstallable(pending: Sequence[str]) -> tuple[str, ...]:
    split = removals.split_removals(pending)
    return (*split.apt, *split.debs, *(f"{flatpak.PREFIX}{i}" for i in split.flatpak))


def _print_pending(logger: Logger, pending: Sequence[str]) -> None:
    uninstallable = _uninstallable(pending)
    if uninstallable:
        logger.warn(f"No longer wanted, installed copies would be removed: {', '.join(uninstallable)}.")
    manual = removals.split_removals(pending).manual
    if manual:
        logger.warn(f"Entries dropped, remove manually: {', '.join(manual)}.")


def _answer(ask: Callable[[str], str]) -> str:
    try:
        return ask("Remove these packages? [y/N] ")
    except EOFError:
        print()
        return ""


def _answered_yes(logger: Logger, ask: Callable[[str], str]) -> bool:
    if _answer(ask).strip().lower() in ("y", "yes"):
        return True
    logger.warn("Removals declined; they will be offered again next run.")
    return False


def confirm_removals(
    logger: Logger, pending: Sequence[str], *, prune: bool, interactive: bool,
    ask: Callable[[str], str] = input,
) -> bool:
    _print_pending(logger, pending)
    if not _uninstallable(pending):
        return False
    if prune:
        return True
    if not interactive:
        logger.warn("Removals skipped; pass --prune to apply.")
        return False
    return _answered_yes(logger, ask)


def removal_candidates(t: tooling.Tooling, pending: Sequence[str]) -> tuple[str, ...]:
    """The pending entries still installed, followed by the manual entries."""
    present = removals.installed_only(t, removals.split_removals(pending))
    return (*_entry_names(present), *present.manual)


def _entry_names(split: removals.Split) -> tuple[str, ...]:
    return (*removals.entries_for(split, split.apt), *(f"{flatpak.PREFIX}{app_id}" for app_id in split.flatpak))


def applied_after_removals(
    t: tooling.Tooling, wanted: frozenset[str], pending: Sequence[str], removed: Sequence[str]
) -> tuple[str, ...]:
    left = [name for name in pending if name not in set(removed)]
    still_installed = removals.installed_only(t, removals.split_removals(left))
    return tuple(sorted(wanted | set(_entry_names(still_installed))))


def _approved_removals(args: argparse.Namespace, t: tooling.Tooling, plan: _Install) -> tuple[str, ...]:
    candidates = removal_candidates(t, plan.pending) if plan.pending else ()
    if args.dry_run:
        _print_pending(t.logger, candidates)
        return ()
    confirmed = confirm_removals(
        t.logger, candidates, prune=args.prune, interactive=sys.stdin.isatty(),
    )
    return candidates if confirmed else ()
