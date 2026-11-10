"""Works out what an install would do: the preset, the wanted packages and the pending removals."""
from __future__ import annotations

import argparse
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from dotfiles_setup import (
    apt_packages,
    identity,
    optouts,
    overlay,
    package_sets,
    presets,
    removals,
    state,
    update,
)
from dotfiles_setup.backends import Backend
from dotfiles_setup.env import Env
from dotfiles_setup.log import Logger
from dotfiles_setup.presets import Preset
from dotfiles_setup.result import Result


def _prepare_checkout(args: argparse.Namespace, logger: Logger, dotfiles_dir: Path) -> Path | None:
    update.pull_if_behind(dotfiles_dir, logger)
    overlay_root = overlay.find_overlay_root()
    update.pull_overlay_if_git(overlay_root, logger)
    if not logger.dry_run_notice("Would ensure git identity (~/.gitconfig.local)."):
        identity.ensure_git_identity(force=args.reconfigure, overlay_root=overlay_root)
    return overlay_root


def _resolve_preset_name(args: argparse.Namespace, prior: state.MachineState | None, logger: Logger) -> str | None:
    if args.preset:
        return args.preset
    if prior is None:
        return None
    logger.info(f"Using saved preset '{prior.preset_name}'.")
    return prior.preset_name


def _build_plan(
    args: argparse.Namespace, logger: Logger, env: Env, preset_name: str, prior: state.MachineState | None
) -> Result[_Install]:
    overlay_root = _prepare_checkout(args, logger, env.dotfiles_dir)
    loaded = presets.load_preset(env.dotfiles_dir / "presets", preset_name)
    return loaded.and_then(
        lambda preset: presets.resolve_packages(env.dotfiles_dir / "packages", preset).map(
            lambda names: _plan(logger, env, preset, names, overlay_root, prior)
        )
    )


def _plan(
    logger: Logger, env: Env, preset: Preset, logical_names: tuple[str, ...],
    overlay_root: Path | None, prior: state.MachineState | None,
) -> _Install:
    backend = env.backend_factory(env.dotfiles_dir, preset.backend_overrides.get("apt", {}))
    combined = _combined(env, backend, logical_names, overlay_root, preset.name)
    package_file = state.package_dir(env.state_dir) / f"{preset.name}.txt"
    stamp = env.clock().strftime("%Y%m%d%H%M%S")
    backup = optouts.backup_dir(Path.home() / ".local" / "state" / "dotfiles", stamp)
    others = _other_presets(logger, package_file, preset.name, backup, env.dotfiles_dir / "presets")
    loaded = _load_optouts(logger, package_file, combined, backup, migrated=bool(prior and prior.optouts_migrated))
    for stale in package_sets.stale_optouts(loaded.names, combined, backend.resolve_name):
        logger.warn(f"Opt-out '{stale}' in {package_file} matches no package in {preset.name}.")
    wanted = package_sets.wanted(combined, loaded.names, backend.resolve_name)
    pending = _pending(logger, _Prior(prior, preset.name, overlay_root), wanted, loaded, backend.resolve_name)
    return _Install(
        preset, backend, combined, package_file, wanted, pending, overlay_root, env.dotfiles_dir, prior, stamp,
        loaded, backup, others,
    )


def _combined(
    env: Env, backend: Backend, logical_names: tuple[str, ...], overlay_root: Path | None, preset_name: str,
) -> tuple[str, ...]:
    overlay_names = overlay.overlay_package_names(overlay_root, preset_name)
    pins = apt_packages.pin_entries(env.dotfiles_dir / "packages" / "github_bins.txt")
    return tuple(sorted({*combine_package_names(backend, logical_names, overlay_names), *pins}))


@dataclass(frozen=True)
class _Optouts:
    names: frozenset[str]
    created: frozenset[str] = frozenset()
    fork_only: tuple[str, ...] = ()
    from_legacy: bool = False


@dataclass(frozen=True)
class _Prior:
    state: state.MachineState | None
    preset_name: str
    overlay_root: Path | None

    def applied(self) -> tuple[str, ...] | None:
        if self.state is None or self.state.preset_name != self.preset_name:
            return None
        return self.state.applied_package_names

    def missing_overlay(self) -> str | None:
        saved = self.state.overlay_root if self.state else None
        return saved if self.overlay_root is None else None


def _pending(
    logger: Logger, prior: _Prior, wanted: frozenset[str], loaded: _Optouts, resolve: Callable[[str], str],
) -> tuple[str, ...]:
    applied = prior.applied() or ()
    missing = prior.missing_overlay()
    if missing is not None:
        logger.warn(f"Private overlay not found: skipping removals (last install used {missing}).")
        return ()
    created = {resolve(name) for name in loaded.created}
    candidates = {*package_sets.pending_removals(applied, wanted), *loaded.fork_only} - created
    return tuple(sorted(candidates - _moved(logger, candidates, wanted)))


def _moved(logger: Logger, candidates: set[str], wanted: frozenset[str]) -> set[str]:
    moved = removals.moved_entries(candidates, wanted)
    for entry in moved:
        logger.warn(f"{entry} moved to another manager; keeping {removals.dpkg_name(entry)}.")
    return set(moved)


def _other_presets(
    logger: Logger, package_file: Path, keep: str, backup: Path, presets_dir: Path,
) -> tuple[Path, ...]:
    others = optouts.other_preset_files(package_file.parent, keep, presets.preset_names(presets_dir))
    verb = "Would move" if logger.dry_run else "Will move"
    if others:
        names = ", ".join(p.name for p in others)
        logger.warn(f"{verb} other presets' package files {names} to {backup} after a successful install.")
    return others


def _load_optouts(
    logger: Logger, package_file: Path, combined: tuple[str, ...], backup: Path, *, migrated: bool,
) -> _Optouts:
    if not optouts.is_legacy(package_file):
        return _Optouts(optouts.read_optouts(package_file))
    if migrated:
        logger.warn(f"{package_file} has no header line '{optouts.HEADER}'; reading it as opt-outs.")
        return _Optouts(optouts.read_optouts(package_file))
    return _migrate_fork(logger, package_file, combined, backup)


def _migrate_fork(logger: Logger, package_file: Path, combined: tuple[str, ...], backup: Path) -> _Optouts:
    unpinned = tuple(n for n in combined if not n.startswith(apt_packages.PIN_PREFIX))
    migrated = optouts.plan_migration(package_file, unpinned)
    verb = "Would migrate" if logger.dry_run else "Will migrate"
    logger.warn(f"{verb} {package_file} to an opt-out file after a successful install; backup in {backup}.")
    if migrated.fork_only:
        logger.warn(f"Packages only in the old file: {', '.join(migrated.fork_only)}.")
    return _Optouts(migrated.optouts, migrated.optouts, migrated.fork_only, from_legacy=True)


def combine_package_names(
    backend: Backend, logical_names: tuple[str, ...], overlay_names: tuple[str, ...]
) -> tuple[str, ...]:
    return tuple(sorted({backend.resolve_name(n) for n in (*logical_names, *overlay_names)}))


@dataclass(frozen=True)
class _Install:
    preset: Preset
    backend: Backend
    combined: tuple[str, ...]
    package_file: Path
    wanted: frozenset[str]
    pending: tuple[str, ...]
    overlay_root: Path | None
    dotfiles_dir: Path
    prior: state.MachineState | None
    stamp: str
    loaded: _Optouts
    backup: Path
    other_presets: tuple[Path, ...] = ()
