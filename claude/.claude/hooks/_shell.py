"""Shell tokenizing shared by the Claude Code hooks in this directory."""
from __future__ import annotations

import re
import shlex

SEPARATORS = frozenset({"&&", "||", ";", "|"})
CONTROL_OPERATOR = re.compile(r"[()]*[&|;][()&|;]*")


def tokenize(command: str) -> list[str]:
    """Splits `command` into words and operator tokens (`&&`, `|`, `;`, `>`, ...) with POSIX quoting; `#` is not a comment. Raises ValueError on bad quoting."""
    lex = shlex.shlex(command, posix=True, punctuation_chars=True)
    lex.whitespace_split = True
    lex.commenters = ""
    return list(lex)


def split_segments(tokens: list[str]) -> list[list[str]]:
    """Splits tokens into the commands between control operators (`&&`, `||`, `;`, `|`, `&`, `|&`, `;;`)."""
    segments: list[list[str]] = [[]]
    for token in tokens:
        if CONTROL_OPERATOR.fullmatch(token):
            segments.append([])
        else:
            segments[-1].append(token)
    return segments


def _quote_end(command: str, start: int) -> int:
    quote, i = command[start], start + 1
    backslash_escapes = quote == '"' or command[start - 1:start] == "$"
    while i < len(command) and command[i] != quote:
        i += 2 if command[i] == "\\" and backslash_escapes else 1
    return min(i + 1, len(command))


def command_lines(command: str) -> list[str]:
    """Splits `command` at unquoted newlines and drops unquoted `#` comments; quoted newlines and `#` stay."""
    lines, current, i, word_start = [], "", 0, True
    while i < len(command):
        char = command[i]
        if char in "'\"":
            end = _quote_end(command, i)
            current, i, word_start = current + command[i:end], end, False
        elif char == "\\":
            current, i, word_start = current + ("" if command[i:i + 2] == "\\\n" else command[i:i + 2]), i + 2, False
        elif char == "\n":
            lines.append(current)
            current, i, word_start = "", i + 1, True
        elif char == "#" and word_start:
            i = command.find("\n", i) if "\n" in command[i:] else len(command)
        else:
            current, i, word_start = current + char, i + 1, char in " \t;|&("
    return [*lines, current]
