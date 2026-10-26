"""Argument parsing and entry point for dotfiles-setup. Port of the
argument-parsing block and startup banner in bin/setup.sh's main()."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
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
    tooling,
    tools,
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

    run: RunFn = field(default_factory=lambda: subprocess.run)
    clock: Callable[[], datetime] = field(default_factory=lambda: lambda: datetime.now(UTC))
    claude_home: Path = field(default_factory=lambda: _claude_home())
    state_dir: Path = field(default_factory=lambda: state.state_dir())
    dotfiles_dir: Path = field(default_factory=lambda: _dotfiles_dir())
    backend_factory: BackendFactory = _apt_backend

    def now_iso(self) -> str:
        return self.clock().isoformat()


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


def _save_state(env: Env, plan: _Install) -> None:
    prior = plan.prior
    state.save_state(state.MachineState(
        preset_name=plan.preset.name,
        backend=plan.backend.name,
        package_file=str(plan.package_file),
        applied_package_names=plan.combined,
        overlay_root=str(plan.overlay_root) if plan.overlay_root else None,
        created_at=prior.created_at if prior else env.now_iso(),
        updated_at=env.now_iso(),
    ), state.state_file(env.state_dir))


def _sync_foothold(logger: Logger, preset: Preset, claude_dir: Path, prior: state.MachineState | None) -> None:
    profile_path = claude_dir / preset.claude_settings if preset.claude_settings else None
    installed = foothold.install_foothold(logger, preset.name, profile_path)
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
    overlay_names = overlay.overlay_package_names(overlay_root, preset.name)
    combined = combine_package_names(backend, logical_names, overlay_names)
    package_file = state.package_dir(env.state_dir) / f"{preset.name}.txt"
    previous_names = prior.applied_package_names if prior and prior.preset_name == preset.name else None
    _reconcile_packages(logger, package_file, combined, previous_names)
    return _Install(preset, backend, combined, package_file, overlay_root, env.dotfiles_dir, prior)


def combine_package_names(
    backend: Backend, logical_names: tuple[str, ...], overlay_names: tuple[str, ...]
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
    backend: Backend
    combined: tuple[str, ...]
    package_file: Path
    overlay_root: Path | None
    dotfiles_dir: Path
    prior: state.MachineState | None


def _tool_hooks(logger: Logger, env: Env, plan: _Install) -> tuple[Callable[[], bool], Callable[[], bool]]:
    t = tools.Tooling(
        logger, Path.home(), run=env.run,
        fetch=tooling.fetch_https, download=tooling.download_https, redirect=tooling.redirect_location,
    )

    def names() -> set[str]:
        return presets.package_names(plan.package_file.read_text())

    return (lambda: tools.install_tools(t, names()), lambda: tools.install_post_apt_tools(t, names()))


def _apply_install(args: argparse.Namespace, logger: Logger, env: Env, plan: _Install) -> int:
    claude_dir = env.state_dir / "claude-profiles"
    _write_claude_profile(logger, plan.preset, plan.dotfiles_dir, claude_dir, plan.overlay_root, plan.preset.name)
    claude_settings = _merged_claude_settings(plan.dotfiles_dir, plan.overlay_root)
    _write_claude_settings(logger, claude_settings, env)
    tools_hook, post_apt_hook = _tool_hooks(logger, env, plan)
    result = plan.backend.install(
        plan.package_file, preset_name=plan.preset.name, claude_profile_dir=claude_dir,
        dry_run=args.dry_run, private_root=plan.overlay_root, verbosity=args.verbosity,
        force_stow=args.force, tools_hook=tools_hook, post_apt_hook=post_apt_hook, run=env.run,
    )
    if not result.succeeded:
        _log_install_failure(logger, result)
        return result.returncode
    _finish_install(args, logger, env, plan, claude_settings)
    return 0


def _finish_install(
    args: argparse.Namespace, logger: Logger, env: Env, plan: _Install, claude_settings: dict[str, Any]
) -> None:
    claude_dir = env.state_dir / "claude-profiles"
    claude_plugins.update_claude_plugins(logger, claude_settings)
    _sync_foothold(logger, plan.preset, claude_dir, plan.prior)
    plan.backend.print_completion(dry_run=args.dry_run, run=env.run)
    if not args.dry_run:
        _save_state(env, plan)
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

    return 1


if __name__ == "__main__":
    sys.exit(main())
