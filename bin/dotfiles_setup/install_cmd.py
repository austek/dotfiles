"""The `dfctl apply` command (alias `install`): plan, ask, apply, then persist."""
from __future__ import annotations

import argparse
import dataclasses
import sys
from typing import Any

from dotfiles_setup import (
    claude_plugins,
    foothold,
    install_flow,
    overlay,
    overlay_migrate,
    path_dirs,
    rollback,
    state,
    tooling,
    update_stamp,
    worktree,
)
from dotfiles_setup.approval import _approved_removals, removal_candidates
from dotfiles_setup.backends import InstallResult
from dotfiles_setup.claude_settings import (
    _merged_claude_settings,
    _settings_drift_exit_code,
    _write_claude_settings,
)
from dotfiles_setup.env import Env, _tooling
from dotfiles_setup.log import Logger
from dotfiles_setup.persist import _persist
from dotfiles_setup.plan import (
    _build_plan,
    _Install,
    _resolve_preset_name,
    ensure_identity,
)
from dotfiles_setup.plan_confirm import confirm_plan
from dotfiles_setup.plan_types import StepPlan
from dotfiles_setup.presets import Preset
from dotfiles_setup.result import Err, Ok, Result
from dotfiles_setup.step_plans import build_step_plans
from dotfiles_setup.transcript import Transcript, open_transcript

PERSIST_FAILED_EXIT_CODE = 4
PATH_LIST_FAILED_EXIT_CODE = 2
TRANSCRIPT_DIR = ".local/state/dotfiles/logs"


def _log_install_failure(logger: Logger, result: InstallResult) -> None:
    logger.error(result.stdout or f"The install failed with exit code {result.returncode}. See output above.")


def _sync_foothold(logger: Logger, preset: Preset, path_entries: tuple[str, ...]) -> None:
    foothold.sync_footholds(logger, preset.footholds, path_entries)


def _refuses_worktree(args: argparse.Namespace, env: Env) -> bool:
    roots = (env.dotfiles_dir, overlay.find_overlay_root())
    linked = next((root for root in roots if root is not None and worktree.is_linked_worktree(root)), None)
    if args.dry_run or linked is None:
        return False
    Logger(dry_run=False, verbosity=args.verbosity).error(
        f"Refusing to install with the linked worktree {linked} as a dotfiles checkout: stow would link /etc and "
        "$HOME into it. Use the main checkouts, or pass --dry-run.")
    return True


def _open_transcript(args: argparse.Namespace, env: Env) -> Transcript | None:
    if args.dry_run:
        return None
    return open_transcript(env.home / TRANSCRIPT_DIR, env.clock().strftime("%Y%m%d-%H%M%S"))


def _run_install(args: argparse.Namespace, env: Env) -> int:
    if _refuses_worktree(args, env):
        return 1
    logger = Logger(dry_run=args.dry_run, verbosity=args.verbosity, transcript=_open_transcript(args, env))
    if logger.transcript is not None:
        logger.info(f"Transcript: {logger.transcript.path}")
    if args.dry_run:
        logger.warn("=== DRY-RUN MODE: No changes will be made ===")
    logger.step("Starting Ubuntu Dotfiles Setup...")
    drift_exit_code = _settings_drift_exit_code(args, logger, env)
    if drift_exit_code is not None:
        return drift_exit_code
    return _install_for_preset(args, logger, env)


def _install_for_preset(args: argparse.Namespace, logger: Logger, env: Env) -> int:
    prior = state.load_state(state.state_file(env.state_dir))
    preset_name = _resolve_preset_name(args, prior, logger)
    if preset_name is None:
        logger.error("No preset saved on this machine; pass --preset <name>.")
        return 2
    match _build_plan(logger, env, preset_name, prior):
        case Err(error=message):
            logger.error(message)
            return 1
        case Ok(value=plan):
            return _apply_install(args, logger, env, plan)


def _rollback_context(logger: Logger, env: Env, plan: _Install) -> rollback.RollbackContext:
    t = _tooling(logger, env)
    return rollback.RollbackContext(t, rollback.RollbackLog.for_home(t.home), plan.dotfiles_dir, plan.overlay_root)


def _flow_inputs(
    t: tooling.Tooling, env: Env, plan: _Install, args: argparse.Namespace, approved: tuple[str, ...] = (),
    plans: tuple[StepPlan, ...] = (),
) -> install_flow.FlowInputs:
    return install_flow.FlowInputs(
        t, plan.dotfiles_dir, plan.preset.name, plan.wanted, plan.overlay_root,
        args.force, plan.stamp, euid=env.euid(), system=args.system,
        upgrade=args.upgrade, removals=approved, interactive=sys.stdin.isatty(), plans=plans,
    )


def _apply_install(args: argparse.Namespace, logger: Logger, env: Env, plan: _Install) -> int:
    match path_dirs.load(plan.dotfiles_dir, plan.overlay_root):
        case Err(error=message):
            logger.error(message)
            return PATH_LIST_FAILED_EXIT_CODE
        case Ok(value=path_entries):
            return _apply_with_path(args, logger, env, plan, path_entries)


def _apply_with_path(
    args: argparse.Namespace, logger: Logger, env: Env, plan: _Install, path_entries: tuple[str, ...],
) -> int:
    t = _tooling(logger, env)
    if _overlay_refused(args, t):
        return 1
    plans = _step_plans(args, t, plan)
    stop = _confirmed(args, t, plans)
    if stop is not None:
        return stop
    moved = _migrated(args, t, plan)
    if moved is None:
        return 1
    ensure_identity(args, logger, moved.overlay_root)
    return _approve_and_run(args, logger, env, moved, path_entries, plans)


def _approve_and_run(
    args: argparse.Namespace, logger: Logger, env: Env, plan: _Install, path_entries: tuple[str, ...],
    plans: tuple[StepPlan, ...],
) -> int:
    t = _tooling(logger, env)
    claude_settings = _merged_claude_settings(plan.dotfiles_dir, plan.overlay_root, plan.preset, env.home, path_entries)
    match _approval(args, t, plan):
        case Err(error=message):
            logger.error(message)
            return install_flow.INTERRUPTED_EXIT_CODE
        case Ok(value=approved):
            # Before the steps: the cozempic install creates ~/.claude/settings.json when it is absent.
            _write_claude_settings(logger, claude_settings, env)
            inputs = _flow_inputs(t, env, plan, args, approved, plans)
            return _run_flow(args, env, plan, claude_settings, path_entries, inputs)


def _overlay_refused(args: argparse.Namespace, t: tooling.Tooling) -> bool:
    refused = overlay_migrate.pending_migration() is overlay_migrate.Migration.REFUSE_WORKTREE
    return refused and not args.dry_run and not overlay_migrate.refuse_worktree(t)


def _migrated(args: argparse.Namespace, t: tooling.Tooling, plan: _Install) -> _Install | None:
    """The plan with the overlay path as it is after the move; None when the migration fails."""
    if args.dry_run:
        return plan
    if not overlay_migrate.migrate_legacy_overlay(t, rollback.RollbackLog.for_home(t.home)):
        return None
    return dataclasses.replace(plan, overlay_root=overlay.find_overlay_root())


def _step_plans(args: argparse.Namespace, t: tooling.Tooling, plan: _Install) -> tuple[StepPlan, ...]:
    candidates = removal_candidates(t, plan.pending) if plan.pending else ()
    return build_step_plans(
        t, plan.dotfiles_dir, plan.wanted, candidates, upgrade=args.upgrade, prune=args.prune, system=args.system,
        overlay_root=plan.overlay_root, preset_name=plan.preset.name,
    )


def _confirmed(args: argparse.Namespace, t: tooling.Tooling, plans: tuple[StepPlan, ...]) -> int | None:
    """None when the apply goes on, else the exit code to stop with."""
    try:
        return confirm_plan(
            t.logger, plans, yes=args.yes, interactive=sys.stdin.isatty(), dry_run=args.dry_run,
        )
    except KeyboardInterrupt:
        t.logger.say("")
        t.logger.error("Interrupted before any install step.")
        return install_flow.INTERRUPTED_EXIT_CODE


def _approval(args: argparse.Namespace, t: tooling.Tooling, plan: _Install) -> Result[tuple[str, ...]]:
    try:
        return Ok(_approved_removals(args, t, plan))
    except KeyboardInterrupt:
        print()
        return Err("Interrupted before any install step.")


def _run_flow(
    args: argparse.Namespace, env: Env, plan: _Install, claude_settings: dict[str, Any],
    path_entries: tuple[str, ...], inputs: install_flow.FlowInputs,
) -> int:
    logger = inputs.t.logger
    result = install_flow.run_install(inputs)
    if not result.succeeded:
        _log_install_failure(logger, result)
        if result.rollback_pending:
            rollback.offer_rollback(_rollback_context(logger, env, plan), interactive=sys.stdin.isatty())
        return result.returncode
    return _finish_install(args, logger, env, plan, claude_settings, path_entries, inputs)


def _finish_install(
    args: argparse.Namespace, logger: Logger, env: Env, plan: _Install, claude_settings: dict[str, Any],
    path_entries: tuple[str, ...], inputs: install_flow.FlowInputs,
) -> int:
    claude_plugins.update_claude_plugins(logger, claude_settings)
    _sync_foothold(logger, plan.preset, path_entries)
    if not (args.dry_run or _persist(logger, env, plan, inputs)):
        return PERSIST_FAILED_EXIT_CODE
    if not args.dry_run:
        update_stamp.record_apply(logger, env.home, env.clock())
    install_flow.print_completion_banner(logger)
    logger.success(f"Machine preset set to '{plan.preset.name}'.")
    return 0
