import argparse
from pathlib import Path

import pytest

from dotfiles_setup.cli import build_arg_parser

ROOT = Path(__file__).resolve().parent.parent
ZSH = (ROOT / "zsh/.config/zsh/completions/_dotfiles-setup").read_text(encoding="utf-8")
BASH = (ROOT / "bash/.local/share/bash-completion/completions/dotfiles-setup").read_text(encoding="utf-8")


def _subparsers(parser: argparse.ArgumentParser) -> dict[str, argparse.ArgumentParser]:
    found: dict[str, argparse.ArgumentParser] = {}
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            found.update(action.choices)
    return found


def _leaf_parsers() -> dict[str, argparse.ArgumentParser]:
    leaves: dict[str, argparse.ArgumentParser] = {}
    for name, parser in _subparsers(build_arg_parser()).items():
        nested = _subparsers(parser)
        if nested:
            leaves.update({f"{name} {child}": p for child, p in nested.items()})
        else:
            leaves[name] = parser
    return leaves


def _options(parser: argparse.ArgumentParser) -> set[str]:
    return {opt for action in parser._actions for opt in action.option_strings}


@pytest.mark.parametrize("command", sorted(_leaf_parsers()))
def test_every_parser_option_is_completed(command: str):
    options = _options(_leaf_parsers()[command])
    missing_bash = {opt for opt in options if f"{opt} " not in BASH and f"{opt}\"" not in BASH}
    missing_zsh = {opt for opt in options if opt not in ZSH}
    assert not missing_bash, f"bash completion lacks {sorted(missing_bash)} for '{command}'"
    assert not missing_zsh, f"zsh completion lacks {sorted(missing_zsh)} for '{command}'"
