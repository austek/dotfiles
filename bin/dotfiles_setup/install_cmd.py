"""The `dotfiles-setup install` command: plan, ask, apply, then persist."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from dotfiles_setup import (
    claude_plugins,
    foothold,
    install_flow,
    rollback,
    state,
    tooling,
)
from dotfiles_setup.approval import _approved_removals
from dotfiles_setup.backends import InstallResult
from dotfiles_setup.claude_settings import (
    _merged_claude_settings,
    _settings_drift_exit_code,
    _write_claude_settings,
)
from dotfiles_setup.env import Env, _tooling
from dotfiles_setup.log import Logger
from dotfiles_setup.persist import _persist
from dotfiles_setup.plan import _build_plan, _Install, _resolve_preset_name
from dotfiles_setup.presets import Preset
from dotfiles_setup.result import Err, Ok, Result
from dotfiles_setup.transcript import Transcript, open_transcript

PERSIST_FAILED_EXIT_CODE = 4
TRANSCRIPT_DIR = ".local/state/dotfiles/logs"


def _log_install_failure(logger: Logger, result: InstallResult) -> None:
    logger.error(result.stdout or f"The install failed with exit code {result.returncode}. See output above.")


def _sync_foothold(logger: Logger, preset: Preset) -> None:
    foothold.sync_footholds(logger, preset.footholds)


def _in_linked_worktree(dotfiles_dir: Path) -> bool:
    """A linked worktree has a `.git` file pointing at the main checkout; the main checkout has a `.git` directory."""
    return (dotfiles_dir / ".git").is_file()


def _refuses_worktree(args: argparse.Namespace, env: Env) -> bool:
    if args.dry_run or not _in_linked_worktree(env.dotfiles_dir):
        return False
    Logger(dry_run=False, verbosity=args.verbosity).error(
        f"Refusing to install from the linked worktree {env.dotfiles_dir}: stow would link /etc and "
        "$HOME into it. Run the install from the main checkout, or pass --dry-run.")
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
    match _build_plan(args, logger, env, preset_name, prior):
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
) -> install_flow.FlowInputs:
    return install_flow.FlowInputs(
        t, plan.dotfiles_dir, plan.preset.name, plan.wanted, plan.overlay_root,
        args.force, plan.stamp, euid=env.euid(), system=args.system,
        upgrade=args.upgrade, removals=approved, interactive=sys.stdin.isatty(),
    )


def _apply_install(args: argparse.Namespace, logger: Logger, env: Env, plan: _Install) -> int:
    claude_settings = _merged_claude_settings(plan.dotfiles_dir, plan.overlay_root, plan.preset, env.home)
    t = _tooling(logger, env)
    match _approval(args, t, plan):
        case Err(error=message):
            logger.error(message)
            return install_flow.INTERRUPTED_EXIT_CODE
        case Ok(value=approved):
            # Before the steps: the cozempic install creates ~/.claude/settings.json when it is absent.
            _write_claude_settings(logger, claude_settings, env)
            return _run_flow(args, env, plan, claude_settings, _flow_inputs(t, env, plan, args, approved))


def _approval(args: argparse.Namespace, t: tooling.Tooling, plan: _Install) -> Result[tuple[str, ...]]:
    try:
        return Ok(_approved_removals(args, t, plan))
    except KeyboardInterrupt:
        print()
        return Err("Interrupted before any install step.")


def _run_flow(
    args: argparse.Namespace, env: Env, plan: _Install, claude_settings: dict[str, Any],
    inputs: install_flow.FlowInputs,
) -> int:
    logger = inputs.t.logger
    result = install_flow.run_install(inputs)
    if not result.succeeded:
        _log_install_failure(logger, result)
        if result.rollback_pending:
            rollback.offer_rollback(_rollback_context(logger, env, plan), interactive=sys.stdin.isatty())
        return result.returncode
    return _finish_install(args, logger, env, plan, claude_settings, inputs)


def _finish_install(
    args: argparse.Namespace, logger: Logger, env: Env, plan: _Install, claude_settings: dict[str, Any],
    inputs: install_flow.FlowInputs,
) -> int:
    claude_plugins.update_claude_plugins(logger, claude_settings)
    _sync_foothold(logger, plan.preset)
    if not (args.dry_run or _persist(logger, env, plan, inputs)):
        return PERSIST_FAILED_EXIT_CODE
    install_flow.print_completion_banner(logger)
    logger.success(f"Machine preset set to '{plan.preset.name}'.")
    return 0
