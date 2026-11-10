"""Entry point for dotfiles-setup."""
from __future__ import annotations

import argparse
import sys

from dotfiles_setup import foothold, overlay, private, state
from dotfiles_setup.env import Env
from dotfiles_setup.install_cmd import _run_install
from dotfiles_setup.log import Logger
from dotfiles_setup.parser import build_arg_parser

__all__ = ["Env", "build_arg_parser", "main"]


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
    return 0 if foothold.restart_footholds(logger, run=env.run) else 1


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
