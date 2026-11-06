"""Argument parsing and entry point for dotfiles-setup."""
from __future__ import annotations

import argparse
import os
import sys
import tempfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from dotfiles_setup import (
    apt_packages,
    checksums,
    claude_plugins,
    flatpak,
    foothold,
    identity,
    install_flow,
    optouts,
    overlay,
    package_sets,
    presets,
    private,
    removals,
    rollback,
    settings_drift,
    state,
    tooling,
    update,
)
from dotfiles_setup.backends import Backend, InstallResult
from dotfiles_setup.log import Logger
from dotfiles_setup.presets import Preset
from dotfiles_setup.result import Err, Ok, Result

DRIFT_EXIT_CODE = 3
SETTINGS_FILE = "settings.json"
RunFn = Callable[..., Any]
BackendFactory = Callable[[Path, dict[str, str]], Backend]


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


_DRY_RUN_HELP = "Show what would be done without executing commands."
_EPILOG = (
    "Examples:\n"
    "  dotfiles-setup install --preset work\n"
    "  dotfiles-setup install  (reuses the preset saved on this machine)\n"
    "  dotfiles-setup install --preset personal --dry-run\n"
    "  dotfiles-setup install --preset homelab -v\n"
    "  dotfiles-setup private clone --repo git@github.com:you/dotfiles-private.git\n"
)
_VERBOSITY_FLAGS = (
    (("-v", "--verbose"), 1, "Show step-by-step progress (INFO/SUCCESS messages)."),
    (("-vv",), 2, "Also show raw output from apt/stow/dpkg/etc."),
    (("-vvv",), 3, "Full debug: also enable command tracing."),
)


def _add_install_flags(install_p: argparse.ArgumentParser) -> None:
    install_p.add_argument(
        "--preset",
        help="Machine profile to set up. Overrides the preset saved on this machine; required on the first run.",
    )
    install_p.add_argument("--dry-run", action="store_true", help=_DRY_RUN_HELP)
    install_p.add_argument(
        "--reconfigure", action="store_true", help="Re-prompt for git identity even if already configured."
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
    system_g = install_p.add_mutually_exclusive_group()
    system_g.add_argument(
        "--system", dest="system", action="store_const", const="always",
        help="Always run the sudo steps (apt, snapd, apt sources, docker group, login shell).",
    )
    system_g.add_argument(
        "--no-system", dest="system", action="store_const", const="never",
        help="Skip the sudo steps and run only the user-level ones.",
    )
    install_p.add_argument(
        "--upgrade",
        action="store_true",
        help="Also upgrade every installed apt package (dist-upgrade) and update Flatpak apps. Forces the sudo steps.",
    )
    install_p.add_argument(
        "--prune",
        action="store_true",
        help=(
            "Uninstall installed packages the repo or overlay dropped, or that you opted out of, "
            "without asking for confirmation."
        ),
    )
    install_p.set_defaults(system="auto")


def _add_verbosity_flags(parser: argparse.ArgumentParser) -> None:
    for flags, amount, help_text in _VERBOSITY_FLAGS:
        parser.add_argument(*flags, nargs=0, action=_AddVerbosity, amount=amount, help=help_text)


def _build_install_parser(sub: Any) -> None:
    install_p = sub.add_parser("install", help="install packages and dotfiles for a machine profile")
    _add_install_flags(install_p)
    _add_verbosity_flags(install_p)
    install_p.set_defaults(verbosity=0)


def _build_clone_parser(private_sub: Any) -> None:
    clone_p = private_sub.add_parser(
        "clone", help="git-clone your private overlay repo so install can auto-detect and layer it"
    )
    clone_p.add_argument(
        "--repo",
        required=True,
        help="Git URL of your private overlay repo, e.g. git@github.com:you/dotfiles-private.git",
    )
    clone_p.add_argument(
        "--dest", type=Path, default=None, help=f"Clone destination (default: {overlay.DEFAULT_OVERLAY_ROOT})."
    )
    clone_p.add_argument("--dry-run", action="store_true", help=_DRY_RUN_HELP)
    clone_p.add_argument(
        "-v", "--verbose", nargs=0, action=_AddVerbosity, amount=1, help="Confirm what was cloned and where."
    )
    clone_p.set_defaults(verbosity=0)


def _build_private_parser(sub: Any) -> None:
    private_p = sub.add_parser(
        "private", help="manage the optional private overlay repo (see AGENTS.md's Presets and Portability)"
    )
    private_sub = private_p.add_subparsers(dest="private_command", metavar="private-command", required=True)
    _build_clone_parser(private_sub)


def _build_restart_parser(foothold_sub: Any) -> None:
    restart_p = foothold_sub.add_parser(
        "restart", help="kill the foothold's tmux session and restart its systemd unit"
    )
    restart_p.add_argument("--dry-run", action="store_true", help=_DRY_RUN_HELP)
    restart_p.add_argument(
        "-v", "--verbose", nargs=0, action=_AddVerbosity, amount=1, help="Confirm what was restarted."
    )
    restart_p.set_defaults(verbosity=0)


def _build_foothold_parser(sub: Any) -> None:
    foothold_p = sub.add_parser(
        "foothold", help="manage the Claude remote foothold of this machine's saved preset"
    )
    foothold_sub = foothold_p.add_subparsers(dest="foothold_command", metavar="foothold-command", required=True)
    _build_restart_parser(foothold_sub)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="dotfiles-setup",
        description="Bootstrap this machine from the dotfiles repo.",
        epilog=_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", metavar="command")
    _build_install_parser(sub)
    _build_private_parser(sub)
    _build_foothold_parser(sub)
    return parser


def _dotfiles_dir() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def _claude_home() -> Path:
    return Path.home() / ".claude"


def _apt_backend(dotfiles_dir: Path, overrides: dict[str, str]) -> Backend:
    from dotfiles_setup.backends.apt import AptBackend

    return AptBackend(dotfiles_dir=dotfiles_dir, backend_overrides=overrides)


@dataclass(frozen=True)
class Env:
    """Collaborators and locations main() uses; defaults resolve when Env() is built, so tests can inject."""

    run: RunFn = field(default_factory=lambda: tooling.run_command)
    clock: Callable[[], datetime] = field(default_factory=lambda: lambda: datetime.now(UTC))
    claude_home: Path = field(default_factory=lambda: _claude_home())
    state_dir: Path = field(default_factory=lambda: state.state_dir())
    dotfiles_dir: Path = field(default_factory=lambda: _dotfiles_dir())
    backend_factory: BackendFactory = _apt_backend
    euid: Callable[[], int] = os.geteuid

    def now_iso(self) -> str:
        return self.clock().isoformat()


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


def _merged_claude_settings(dotfiles_dir: Path, overlay_root: Path | None, preset: Preset) -> dict[str, Any]:
    profile = dotfiles_dir / "claude-profiles" / preset.claude_settings if preset.claude_settings else None
    return overlay.load_preset_settings(
        dotfiles_dir / "claude" / ".claude" / SETTINGS_FILE, profile, overlay_root, preset.name,
    )


def _write_claude_settings(logger: Logger, merged: dict[str, Any], env: Env) -> None:
    target = env.claude_home / SETTINGS_FILE
    if logger.dry_run_notice(f"Would generate {target}."):
        return
    env.claude_home.mkdir(parents=True, exist_ok=True)
    rendered = settings_drift.render(merged)
    _replace_settings_target(target, rendered, env.clock())
    settings_drift.record_baseline(env.state_dir, rendered)


def _settings_drift_exit_code(args: argparse.Namespace, logger: Logger, env: Env) -> int | None:
    target = env.claude_home / SETTINGS_FILE
    diff = settings_drift.drift_diff(target, env.state_dir)
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
    logger.error(result.stdout or f"The install failed with exit code {result.returncode}. See output above.")


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


def _save_state(env: Env, plan: _Install, applied: tuple[str, ...]) -> None:
    prior = plan.prior
    state.save_state(state.MachineState(
        preset_name=plan.preset.name,
        backend=plan.backend.name,
        package_file=str(plan.package_file),
        applied_package_names=applied,
        overlay_root=str(plan.overlay_root) if plan.overlay_root else None,
        created_at=prior.created_at if prior else env.now_iso(),
        updated_at=env.now_iso(),
        optouts_migrated=True,
    ), state.state_file(env.state_dir))


def _sync_foothold(logger: Logger, preset: Preset, prior: state.MachineState | None) -> None:
    installed = foothold.install_foothold(logger, preset.name)
    if installed and prior and prior.preset_name != preset.name:
        foothold.retire_foothold(logger, prior.preset_name)


def _run_install(args: argparse.Namespace, env: Env) -> int:
    logger = Logger(dry_run=args.dry_run, verbosity=args.verbosity)
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
    _retire_other_presets(logger, package_file, preset.name, backup)
    loaded = _load_optouts(logger, package_file, combined, backup, migrated=bool(prior and prior.optouts_migrated))
    for stale in package_sets.stale_optouts(loaded.names, combined, backend.resolve_name):
        logger.warn(f"Opt-out '{stale}' in {package_file} matches no package in {preset.name}.")
    wanted = package_sets.wanted(combined, loaded.names, backend.resolve_name)
    pending = _pending(logger, _Prior(prior, preset.name, overlay_root), wanted, loaded, backend.resolve_name)
    return _Install(
        preset, backend, combined, package_file, wanted, pending, overlay_root, env.dotfiles_dir, prior, stamp,
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
        current = str(self.overlay_root) if self.overlay_root else None
        return saved if saved is not None and saved != current else None


def _pending(
    logger: Logger, prior: _Prior, wanted: frozenset[str], loaded: _Optouts, resolve: Callable[[str], str],
) -> tuple[str, ...]:
    applied = prior.applied()
    if applied is None:
        return ()
    missing = prior.missing_overlay()
    if missing is not None:
        logger.warn(f"Private overlay not found: skipping removals (last install used {missing}).")
        return ()
    created = {resolve(name) for name in loaded.created}
    candidates = {*package_sets.pending_removals(applied, wanted), *loaded.fork_only}
    return tuple(sorted(candidates - created))


def _retire_other_presets(logger: Logger, package_file: Path, keep: str, backup: Path) -> None:
    retired = optouts.retire_other_presets(package_file.parent, keep, backup, dry_run=logger.dry_run)
    verb = "Would move" if logger.dry_run else "Moved"
    if retired:
        logger.warn(f"{verb} other presets' package files {', '.join(retired)} to {backup}.")


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
    migrated = optouts.migrate(package_file, unpinned, backup, dry_run=logger.dry_run)
    verb = "Would migrate" if logger.dry_run else "Migrated"
    logger.warn(f"{verb} {package_file} to an opt-out file; backup in {backup}.")
    if migrated.fork_only:
        logger.warn(f"Packages only in the old file: {', '.join(migrated.fork_only)}.")
    return _Optouts(migrated.optouts, migrated.optouts, migrated.fork_only)


def combine_package_names(
    backend: Backend, logical_names: tuple[str, ...], overlay_names: tuple[str, ...]
) -> tuple[str, ...]:
    return tuple(sorted({backend.resolve_name(n) for n in logical_names} | set(overlay_names)))


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


def _tooling(logger: Logger, env: Env) -> tooling.Tooling:
    return tooling.Tooling(
        logger, Path.home(), run=env.run,
        fetch=tooling.fetch_https, fetch_bytes=tooling.fetch_bytes_https,
        download=tooling.download_https, redirect=tooling.redirect_location,
        checksums=checksums.load(env.dotfiles_dir / "packages" / checksums.FILE_NAME),
    )


def _rollback_context(logger: Logger, env: Env, plan: _Install) -> rollback.RollbackContext:
    t = _tooling(logger, env)
    return rollback.RollbackContext(t, rollback.RollbackLog.for_home(t.home), plan.dotfiles_dir, plan.overlay_root)


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


def _answered_yes(ask: Callable[[str], str]) -> bool:
    try:
        return ask("Remove these packages? [y/N] ").strip().lower() in ("y", "yes")
    except (EOFError, KeyboardInterrupt):
        print()
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
    return _answered_yes(ask)


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


def _flow_inputs(
    t: tooling.Tooling, env: Env, plan: _Install, args: argparse.Namespace, approved: tuple[str, ...] = (),
) -> install_flow.FlowInputs:
    return install_flow.FlowInputs(
        t, plan.dotfiles_dir, plan.preset.name, plan.wanted, plan.overlay_root,
        args.force, plan.stamp, euid=env.euid(), system=args.system,
        upgrade=args.upgrade, removals=approved,
    )


def _apply_install(args: argparse.Namespace, logger: Logger, env: Env, plan: _Install) -> int:
    claude_settings = _merged_claude_settings(plan.dotfiles_dir, plan.overlay_root, plan.preset)
    # Before the steps: the cozempic install creates ~/.claude/settings.json when it is absent.
    _write_claude_settings(logger, claude_settings, env)
    t = _tooling(logger, env)
    inputs = _flow_inputs(t, env, plan, args, _approved_removals(args, t, plan))
    result = install_flow.run_install(inputs)
    if not result.succeeded:
        _log_install_failure(logger, result)
        if result.rollback_pending:
            rollback.offer_rollback(_rollback_context(logger, env, plan), interactive=sys.stdin.isatty())
        return result.returncode
    _finish_install(args, logger, env, plan, claude_settings, inputs)
    return 0


def _finish_install(
    args: argparse.Namespace, logger: Logger, env: Env, plan: _Install, claude_settings: dict[str, Any],
    inputs: install_flow.FlowInputs,
) -> None:
    claude_plugins.update_claude_plugins(logger, claude_settings)
    _sync_foothold(logger, plan.preset, plan.prior)
    install_flow.print_completion_banner(logger)
    if not args.dry_run:
        _save_state(env, plan, applied_after_removals(inputs.t, plan.wanted, plan.pending, inputs.removed))
    logger.success(f"Machine preset set to '{plan.preset.name}'.")


def _run_private_clone(args: argparse.Namespace, env: Env) -> int:
    logger = Logger(dry_run=args.dry_run, verbosity=args.verbosity)
    dest = args.dest if args.dest is not None else overlay.DEFAULT_OVERLAY_ROOT
    if logger.dry_run_notice(f"Would clone {args.repo} to {dest}."):
        return 0
    result = private.clone_overlay(args.repo, dest, run=env.run)
    if not result.succeeded:
        logger.error(result.stdout or f"git clone exited with code {result.returncode}.")
        return result.returncode
    logger.success(f"Cloned private overlay to {dest}.")
    logger.success("Re-run 'dotfiles-setup install --preset <name>' to layer it in.")
    return 0


def _run_foothold_restart(args: argparse.Namespace, env: Env) -> int:
    logger = Logger(dry_run=args.dry_run, verbosity=args.verbosity)
    saved = state.load_state(state.state_file(env.state_dir))
    if saved is None:
        logger.error("No preset saved on this machine; run 'dotfiles-setup install --preset <name>' first.")
        return 2
    return 0 if foothold.restart_foothold(logger, saved.preset_name, run=env.run) else 1


def main(argv: list[str] | None = None, env: Env | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    env = env if env is not None else Env()

    if args.command is None:
        parser.print_help()
        return 1

    if args.command == "install":
        return _run_install(args, env)

    if args.command == "private" and args.private_command == "clone":
        return _run_private_clone(args, env)

    if args.command == "foothold" and args.foothold_command == "restart":
        return _run_foothold_restart(args, env)

    return 1


if __name__ == "__main__":
    sys.exit(main())
