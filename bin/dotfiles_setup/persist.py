"""Saves what an install did: the migrated opt-out file, state.json and the other presets' backups."""
from __future__ import annotations

from pathlib import Path

from dotfiles_setup import install_flow, optouts, state
from dotfiles_setup.approval import applied_after_removals
from dotfiles_setup.env import Env
from dotfiles_setup.log import Logger
from dotfiles_setup.plan import _Install, _Prior
from dotfiles_setup.result import Err, Ok, Result


def _save_state(
    env: Env, plan: _Install, applied: tuple[str, ...], overlay_root: str | None, *, migrated: bool,
) -> None:
    prior = plan.prior
    state.save_state(state.MachineState(
        preset_name=plan.preset.name,
        backend=plan.backend.name,
        package_file=str(plan.package_file),
        applied_package_names=applied,
        overlay_root=overlay_root,
        created_at=prior.created_at if prior else env.now_iso(),
        updated_at=env.now_iso(),
        optouts_migrated=migrated,
    ), state.state_file(env.state_dir))


def _persist(logger: Logger, env: Env, plan: _Install, inputs: install_flow.FlowInputs) -> bool:
    """Writes the migration, the state and the other presets' backups; False when any of them failed."""
    written = _write_migration(logger, plan)
    applied, overlay_root = _saved_applied(inputs, plan)
    if isinstance(written, Err):
        applied = _Prior(plan.prior, plan.preset.name, plan.overlay_root).applied() or ()
    if not _state_saved(logger, env, plan, (applied, overlay_root), written):
        return False
    return isinstance(written, Ok) and _retire_other_presets(logger, plan)


def _state_saved(
    logger: Logger, env: Env, plan: _Install, saved: tuple[tuple[str, ...], str | None], written: Result[Path | None],
) -> bool:
    try:
        _save_state(env, plan, *saved, migrated=isinstance(written, Ok))
    except OSError as error:
        logger.error(f"Could not save the install state to {state.state_file(env.state_dir)}: {error}.")
        match written:
            case Ok(value=Path() as backup_copy):
                _undo_migration(logger, plan, backup_copy)
        return False
    return True


def _undo_migration(logger: Logger, plan: _Install, backup_copy: Path) -> None:
    try:
        optouts.restore_from_backup(plan.package_file, backup_copy)
    except OSError as error:
        logger.error(
            f"Could not restore {plan.package_file}: {error}. It now has a header line, so the next run reads it "
            "as plain opt-outs and will offer to remove the names the migration created."
        )
        return
    logger.warn(f"Restored {plan.package_file} from {backup_copy}; the next install retries the migration.")


def _retire_other_presets(logger: Logger, plan: _Install) -> bool:
    if not plan.other_presets:
        return True
    try:
        optouts.move_to_backup(plan.other_presets, plan.backup)
    except OSError as error:
        logger.error(f"Could not move {', '.join(map(str, plan.other_presets))} to {plan.backup}: {error}.")
        return False
    logger.warn(f"Moved other presets' package files {', '.join(p.name for p in plan.other_presets)} to {plan.backup}.")
    return True


def _write_migration(logger: Logger, plan: _Install) -> Result[Path | None]:
    """Ok with the legacy file's backup copy, Ok(None) when nothing needed migrating, Err when the write failed."""
    if not plan.loaded.from_legacy:
        return Ok(None)
    try:
        backup_copy = optouts.write_migration(plan.package_file, plan.loaded.names, plan.backup)
    except OSError as error:
        logger.error(
            f"Could not migrate {plan.package_file}: {error}. "
            "The file stays legacy; the next install retries the migration."
        )
        return Err(str(error))
    logger.warn(f"Migrated {plan.package_file} to an opt-out file; backup in {backup_copy}.")
    return Ok(backup_copy)


def _saved_applied(inputs: install_flow.FlowInputs, plan: _Install) -> tuple[tuple[str, ...], str | None]:
    """The applied list and overlay root to save; a missing overlay keeps the prior ones so removals are offered later."""
    prior = _Prior(plan.prior, plan.preset.name, plan.overlay_root)
    applied, missing = prior.applied(), prior.missing_overlay()
    if applied is not None and missing is not None:
        return tuple(sorted({*applied, *plan.wanted})), missing
    current = str(plan.overlay_root) if plan.overlay_root else None
    return applied_after_removals(inputs.t, plan.wanted, plan.pending, inputs.removed), current
