"""The dotfiles-setup argument parser."""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from dotfiles_setup import overlay


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
        help="Always run the sudo steps (apt installs and removals, snapd, apt sources, docker group, login shell).",
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
            "without asking for confirmation. apt removals run only in the system stage."
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
        "restart", help="kill each foothold's tmux session and restart its systemd unit"
    )
    restart_p.add_argument("--dry-run", action="store_true", help=_DRY_RUN_HELP)
    restart_p.add_argument(
        "-v", "--verbose", nargs=0, action=_AddVerbosity, amount=1, help="Confirm what was restarted."
    )
    restart_p.set_defaults(verbosity=0)


def _build_foothold_parser(sub: Any) -> None:
    foothold_p = sub.add_parser(
        "foothold", help="manage the Claude remote footholds of this machine's saved preset"
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
