"""Argument parsing and entry point for dotfiles-setup. Port of the
argument-parsing block and startup banner in bin/setup.sh's main()."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from dotfiles_setup import (
    claude_plugins,
    foothold,
    identity,
    overlay,
    presets,
    private,
    reconcile,
    settings_drift,
    state,
    update,
)
from dotfiles_setup.backends import InstallResult
from dotfiles_setup.backends.apt import AptBackend
from dotfiles_setup.log import Logger
from dotfiles_setup.presets import Preset

CLAUDE_HOME = Path.home() / ".claude"
DRIFT_EXIT_CODE = 3
SETTINGS_FILE = "settings.json"


class _AddVerbosity(argparse.Action):
    """-v/-vv/-vvv are three distinct flag strings, each adding a fixed
    amount to a shared counter — not repetitions of one flag."""

    def __init__(self, *args, amount: int, **kwargs):
        self._amount = amount
        super().__init__(*args, **kwargs)

    def __call__(
        self,
        parser: argparse.ArgumentParser,
        namespace: argparse.Namespace,
        values: object,
        option_string: str | None = None,
    ) -> None:
        namespace.verbosity = getattr(namespace, "verbosity", 0) + self._amount


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="dotfiles-setup",
        description="Bootstrap this machine from the dotfiles repo.",
        epilog=(
            "Examples:\n"
            "  dotfiles-setup install --preset work\n"
            "  dotfiles-setup install  (reuses the preset saved on this machine)\n"
            "  dotfiles-setup install --preset personal --dry-run\n"
            "  dotfiles-setup install --preset homelab -v\n"
            "  dotfiles-setup private clone --repo git@github.com:you/dotfiles-private.git\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", metavar="command")

    install_p = sub.add_parser(
        "install", help="install packages and dotfiles for a machine profile"
    )
    install_p.add_argument(
        "--preset",
        help="Machine profile to set up. Overrides the preset saved on this machine; required on the first run.",
    )
    install_p.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without executing commands.",
    )
    install_p.add_argument(
        "-v", "--verbose", nargs=0, action=_AddVerbosity, amount=1,
        help="Show step-by-step progress (INFO/SUCCESS messages).",
    )
    install_p.add_argument(
        "-vv", nargs=0, action=_AddVerbosity, amount=2,
        help="Also show raw output from apt/stow/dpkg/etc.",
    )
    install_p.add_argument(
        "-vvv", nargs=0, action=_AddVerbosity, amount=3,
        help="Full debug: also enable command tracing.",
    )
    install_p.add_argument(
        "--reconfigure",
        action="store_true",
        help="Re-prompt for git identity even if already configured.",
    )
    install_p.add_argument(
        "--force",
        action="store_true",
        help="Back up files that block stow (to ~/.local/state/dotfiles/stow-backups/<timestamp>) and stow anyway.",
    )
    install_p.add_argument(
        "--accept-drift",
        action="store_true",
        help="Overwrite ~/.claude/settings.json even if it was edited since the last install (the old file is kept as .bak-<timestamp>).",
    )
    install_p.set_defaults(verbosity=0)

    private_p = sub.add_parser(
        "private", help="manage the optional private overlay repo (see AGENTS.md's Presets and Portability)"
    )
    private_sub = private_p.add_subparsers(dest="private_command", metavar="private-command", required=True)
    clone_p = private_sub.add_parser(
        "clone", help="git-clone your private overlay repo so install can auto-detect and layer it"
    )
    clone_p.add_argument(
        "--repo",
        required=True,
        help="Git URL of your private overlay repo, e.g. git@github.com:you/dotfiles-private.git",
    )
    clone_p.add_argument(
        "--dest",
        type=Path,
        default=None,
        help=f"Clone destination (default: {overlay.DEFAULT_OVERLAY_ROOT}).",
    )
    clone_p.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without executing commands.",
    )
    clone_p.add_argument(
        "-v", "--verbose", nargs=0, action=_AddVerbosity, amount=1,
        help="Confirm what was cloned and where.",
    )
    clone_p.set_defaults(verbosity=0)
    return parser


def _dotfiles_dir() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _write_claude_profile(
    logger: Logger, preset: Preset, dotfiles_dir: Path, claude_dir: Path,
    overlay_root: Path | None, preset_name: str,
) -> None:
    if not preset.claude_settings:
        return
    claude_profile_path = claude_dir / preset.claude_settings
    if logger.dry_run_notice(f"Would write {claude_profile_path}."):
        return
    claude_dir.mkdir(parents=True, exist_ok=True)
    base_path = dotfiles_dir / "claude-profiles" / preset.claude_settings
    merged = overlay.load_claude_settings(base_path, overlay_root, preset_name)
    claude_profile_path.write_text(json.dumps(merged, indent=2) + "\n")


def _stage(target: Path, rendered: str) -> Path:
    descriptor, name = tempfile.mkstemp(dir=target.parent, prefix=f"{target.name}.", suffix=".tmp")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as staged:
            staged.write(rendered)
    except BaseException:
        Path(name).unlink(missing_ok=True)
        raise
    return Path(name)


def _replace_settings_target(target: Path, rendered: str, now: datetime) -> None:
    existing = target.is_file() and not target.is_symlink()
    if existing and target.read_text(encoding="utf-8") == rendered:
        return
    staged = _stage(target, rendered)
    if existing:
        target.rename(target.with_name(f"{target.name}.bak-{now:%Y%m%d%H%M%S}"))
    staged.replace(target)


def _merged_claude_settings(dotfiles_dir: Path, overlay_root: Path | None) -> dict[str, Any]:
    return overlay.load_settings(dotfiles_dir / "claude" / ".claude" / SETTINGS_FILE, overlay_root)


def _write_claude_settings(logger: Logger, merged: dict[str, Any], claude_home: Path) -> None:
    target = claude_home / SETTINGS_FILE
    if logger.dry_run_notice(f"Would generate {target}."):
        return
    claude_home.mkdir(parents=True, exist_ok=True)
    rendered = settings_drift.render(merged)
    _replace_settings_target(target, rendered, datetime.now(UTC))
    settings_drift.record_baseline(state.STATE_DIR, rendered)


def _settings_drift_exit_code(args: argparse.Namespace, logger: Logger) -> int | None:
    target = CLAUDE_HOME / SETTINGS_FILE
    diff = settings_drift.drift_diff(target, state.STATE_DIR)
    if not diff or args.accept_drift:
        return None
    logger.warn(f"{target} was edited since the last install:")
    print(diff, end="")
    if args.dry_run:
        logger.warn("A real install would stop here; pass --accept-drift to overwrite these edits.")
        return None
    logger.error(
        "Stopping before any change. Move the edits into claude/.claude/settings.json or the overlay's "
        "claude-settings/settings.json, or pass --accept-drift to overwrite them (the old file is kept as .bak)."
    )
    return DRIFT_EXIT_CODE


def _log_install_failure(logger: Logger, result: InstallResult) -> None:
    # backends/apt.py streams setup.sh output live; stdout is set only when a caller passes a capturing run (tests).
    if result.stdout:
        logger.error(result.stdout)
    else:
        logger.error(f"setup.sh exited with code {result.returncode}. See output above.")


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


def _save_state(
    backend: AptBackend, preset_name: str, package_file: Path, combined: tuple[str, ...],
    overlay_root: Path | None, prior: state.MachineState | None,
) -> None:
    state.save_state(state.MachineState(
        preset_name=preset_name,
        backend=backend.name,
        package_file=str(package_file),
        applied_package_names=combined,
        overlay_root=str(overlay_root) if overlay_root else None,
        created_at=prior.created_at if prior else _now(),
        updated_at=_now(),
    ))


def _sync_foothold(logger: Logger, preset: Preset, claude_dir: Path, prior: state.MachineState | None) -> None:
    profile_path = claude_dir / preset.claude_settings if preset.claude_settings else None
    installed = foothold.install_foothold(logger, preset.name, profile_path)
    if installed and prior and prior.preset_name != preset.name:
        foothold.retire_foothold(logger, prior.preset_name)


def _run_install(args: argparse.Namespace) -> int:
    logger = Logger(dry_run=args.dry_run, verbosity=args.verbosity)
    if args.dry_run:
        logger.warn("=== DRY-RUN MODE: No changes will be made ===")
    logger.step("Starting Ubuntu Dotfiles Setup...")
    drift_exit_code = _settings_drift_exit_code(args, logger)
    if drift_exit_code is not None:
        return drift_exit_code
    prior = state.load_state()
    preset_name = _resolve_preset_name(args, prior, logger)
    if preset_name is None:
        logger.error("No preset saved on this machine; pass --preset <name>.")
        return 2
    try:
        plan = _build_plan(args, logger, preset_name, prior)
    except FileNotFoundError as exc:
        logger.error(str(exc))
        return 1
    return _apply_install(args, logger, plan)


def _build_plan(
    args: argparse.Namespace, logger: Logger, preset_name: str, prior: state.MachineState | None
) -> _Install:
    dotfiles_dir = _dotfiles_dir()
    overlay_root = _prepare_checkout(args, logger, dotfiles_dir)
    preset = presets.load_preset(dotfiles_dir / "presets", preset_name)
    logical_names = presets.resolve_packages(dotfiles_dir / "packages", preset)
    backend = AptBackend(dotfiles_dir=dotfiles_dir, backend_overrides=preset.backend_overrides.get("apt", {}))
    combined = combine_package_names(backend, logical_names, overlay.overlay_package_names(overlay_root, preset_name))
    package_file = state.PACKAGE_DIR / f"{preset_name}.txt"
    previous_names = prior.applied_package_names if prior and prior.preset_name == preset_name else None
    _reconcile_packages(logger, package_file, combined, previous_names)
    return _Install(preset, backend, combined, package_file, overlay_root, dotfiles_dir, prior)


def combine_package_names(
    backend: AptBackend, logical_names: tuple[str, ...], overlay_names: tuple[str, ...]
) -> tuple[str, ...]:
    return tuple(sorted({backend.resolve_name(n) for n in logical_names} | set(overlay_names)))


def _reconcile_packages(
    logger: Logger, package_file: Path, combined: tuple[str, ...], previous_names: tuple[str, ...] | None
) -> None:
    added, _ = reconcile.reconcile_package_file(package_file, combined, previous_names)
    if added:
        logger.info(f"Added {len(added)} new package(s) to {package_file}")


@dataclass(frozen=True)
class _Install:
    preset: Preset
    backend: AptBackend
    combined: tuple[str, ...]
    package_file: Path
    overlay_root: Path | None
    dotfiles_dir: Path
    prior: state.MachineState | None


def _apply_install(args: argparse.Namespace, logger: Logger, plan: _Install) -> int:
    claude_dir = state.STATE_DIR / "claude-profiles"
    _write_claude_profile(logger, plan.preset, plan.dotfiles_dir, claude_dir, plan.overlay_root, plan.preset.name)
    claude_settings = _merged_claude_settings(plan.dotfiles_dir, plan.overlay_root)
    _write_claude_settings(logger, claude_settings, CLAUDE_HOME)
    result = plan.backend.install(
        plan.package_file, preset_name=plan.preset.name, claude_profile_dir=claude_dir,
        dry_run=args.dry_run, private_root=plan.overlay_root, verbosity=args.verbosity,
        force_stow=args.force, run=subprocess.run,
    )
    if not result.succeeded:
        _log_install_failure(logger, result)
        return result.returncode
    _finish_install(args, logger, plan, claude_dir, claude_settings)
    return 0


def _finish_install(
    args: argparse.Namespace, logger: Logger, plan: _Install, claude_dir: Path, claude_settings: dict[str, Any]
) -> None:
    claude_plugins.update_claude_plugins(logger, claude_settings)
    _sync_foothold(logger, plan.preset, claude_dir, plan.prior)
    plan.backend.print_completion(dry_run=args.dry_run, run=subprocess.run)
    if not args.dry_run:
        _save_state(plan.backend, plan.preset.name, plan.package_file, plan.combined, plan.overlay_root, plan.prior)
    logger.success(f"Machine preset set to '{plan.preset.name}'.")


def _run_private_clone(args: argparse.Namespace) -> int:
    logger = Logger(dry_run=args.dry_run, verbosity=args.verbosity)
    dest = args.dest if args.dest is not None else overlay.DEFAULT_OVERLAY_ROOT
    if logger.dry_run_notice(f"Would clone {args.repo} to {dest}."):
        return 0
    result = private.clone_overlay(args.repo, dest, run=subprocess.run)
    if not result.succeeded:
        logger.error(result.stdout or f"git clone exited with code {result.returncode}.")
        return result.returncode
    logger.success(f"Cloned private overlay to {dest}.")
    logger.success("Re-run 'dotfiles-setup install --preset <name>' to layer it in.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        return 1

    if args.command == "install":
        return _run_install(args)

    if args.command == "private" and args.private_command == "clone":
        return _run_private_clone(args)

    return 1


if __name__ == "__main__":
    sys.exit(main())
