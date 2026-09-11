"""Argument parsing and entry point for dotfiles-setup. Port of the
argument-parsing block and startup banner in bin/setup.sh's main()."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

from dotfiles_setup import identity, overlay, presets, reconcile, state
from dotfiles_setup.backends.apt import AptBackend
from dotfiles_setup.log import Logger

PRESETS = ("work", "personal", "homelab")


class _AddVerbosity(argparse.Action):
    """-v/-vv/-vvv are three distinct flag strings, each adding a fixed
    amount to a shared counter — not repetitions of one flag."""

    def __init__(self, *args, amount: int, **kwargs):
        self._amount = amount
        super().__init__(*args, **kwargs)

    def __call__(self, parser, namespace, values, option_string=None):
        namespace.verbosity = getattr(namespace, "verbosity", 0) + self._amount


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="dotfiles-setup",
        description="Bootstrap this machine from the dotfiles repo.",
        epilog=(
            "Examples:\n"
            "  dotfiles-setup install --preset work\n"
            "  dotfiles-setup install --preset personal --dry-run\n"
            "  dotfiles-setup install --preset homelab -v\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", metavar="command")

    install_p = sub.add_parser(
        "install", help="install packages and dotfiles for a machine profile"
    )
    install_p.add_argument(
        "--preset",
        required=True,
        help="Machine profile to set up.",
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
        help="Re-prompt for git identity and re-detect the local-overlay root even if already configured.",
    )
    install_p.set_defaults(verbosity=0)
    return parser


def _dotfiles_dir() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _run_install(args: argparse.Namespace) -> int:
    logger = Logger(dry_run=args.dry_run, verbosity=args.verbosity)
    if args.dry_run:
        logger.warn("=== DRY-RUN MODE: No changes will be made ===")
    logger.step("Starting Ubuntu Dotfiles Setup...")

    dotfiles_dir = _dotfiles_dir()
    identity.ensure_git_identity(force=args.reconfigure)

    try:
        preset = presets.load_preset(dotfiles_dir / "presets", args.preset)
    except FileNotFoundError as exc:
        logger.error(str(exc))
        return 1

    overlay_root = overlay.find_overlay_root()
    logical_names = presets.resolve_packages(dotfiles_dir / "packages", preset)
    backend = AptBackend(dotfiles_dir=dotfiles_dir, backend_overrides=preset.backend_overrides.get("apt", {}))
    resolved_names = tuple(sorted({backend.resolve_name(n) for n in logical_names}))
    overlay_names = overlay.overlay_package_names(overlay_root, args.preset)
    combined = tuple(sorted(set(resolved_names) | set(overlay_names)))

    prior = state.load_state()
    package_file = state.PACKAGE_DIR / f"{args.preset}.txt"
    previous_names = prior.applied_package_names if prior and prior.preset_name == args.preset else None
    added, _changed = reconcile.reconcile_package_file(package_file, combined, previous_names)
    if added:
        logger.info(f"Added {len(added)} new package(s) to {package_file}")

    claude_dir = state.STATE_DIR / "claude-profiles"
    claude_dir.mkdir(parents=True, exist_ok=True)
    if preset.claude_settings:
        base_path = dotfiles_dir / "claude-profiles" / preset.claude_settings
        merged = overlay.load_claude_settings(base_path, overlay_root, args.preset)
        (claude_dir / preset.claude_settings).write_text(json.dumps(merged, indent=2) + "\n")

    result = backend.install(
        package_file, preset_name=args.preset, claude_profile_dir=claude_dir,
        dry_run=args.dry_run, private_root=overlay_root, run=subprocess.run,
    )

    state.save_state(state.MachineState(
        preset_name=args.preset,
        backend=backend.name,
        package_file=str(package_file),
        applied_package_names=combined,
        overlay_root=str(overlay_root) if overlay_root else None,
        created_at=prior.created_at if prior else _now(),
        updated_at=_now(),
    ))

    if not result.succeeded:
        # setup.sh's own output already streamed live above (backend.install no longer
        # captures it — see apt.py) — result.stdout only ever carries anything when a
        # caller passes a `run` that captures on its own, e.g. tests.
        if result.stdout:
            logger.error(result.stdout)
        else:
            logger.error(f"setup.sh exited with code {result.returncode}. See output above.")
        return result.returncode
    logger.success(f"Machine preset set to '{args.preset}'.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        return 1

    if args.command == "install":
        return _run_install(args)

    return 1


if __name__ == "__main__":
    sys.exit(main())
