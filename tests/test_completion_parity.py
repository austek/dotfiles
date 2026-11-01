import argparse
import re
from pathlib import Path

import pytest
from _completion import complete
from dotfiles_setup.cli import build_arg_parser

ZSH = (
    Path(__file__).resolve().parent.parent / "zsh/.config/zsh/completions/_dotfiles-setup"
).read_text(encoding="utf-8")


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


def _zsh_block(command: str) -> str:
    name = command.split()[0]
    match = re.search(rf"^      {name}\)\n(.*?)(?=^      \w+\)\n|\Z)", ZSH, re.DOTALL | re.MULTILINE)
    assert match, f"zsh completion has no block for '{name}'"
    return match.group(1)


def _zsh_declares(block: str, option: str) -> bool:
    return re.search(rf"(?<![\w-]){re.escape(option)}[,}}]?'?\[", block) is not None or (
        re.search(rf"[{{,]{re.escape(option)}[,}}]", block) is not None
    )


@pytest.mark.parametrize("command", sorted(_leaf_parsers()))
def test_bash_completes_every_parser_option(command: str):
    words = ["dotfiles-setup", *command.split(), "-"]
    offered = set(complete("dotfiles-setup", "_dotfiles_setup_completions", words, len(words) - 1))
    missing = _options(_leaf_parsers()[command]) - offered
    assert not missing, f"bash completion lacks {sorted(missing)} for '{command}'"


@pytest.mark.parametrize("command", sorted(_leaf_parsers()))
def test_zsh_declares_every_parser_option(command: str):
    block = _zsh_block(command)
    missing = {opt for opt in _options(_leaf_parsers()[command]) if not _zsh_declares(block, opt)}
    assert not missing, f"zsh completion lacks {sorted(missing)} for '{command}'"
