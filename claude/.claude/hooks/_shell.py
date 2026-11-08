"""Shell tokenizing shared by the Claude Code hooks in this directory."""
from __future__ import annotations

import re
import shlex

SEPARATORS = frozenset({"&&", "||", ";", "|"})
CONTROL_OPERATOR = re.compile(r"[()]*[&|;][()&|;]*")


class Quoted(str):
    """A word that contained a quoted or escaped control character, so it is an operand and never an operator."""


MASKED = {char: chr(0xE000 + n) for n, char in enumerate("&|;()")}
UNMASK = {mask: char for char, mask in MASKED.items()}


def _mask_quoted(command: str) -> str:
    """`command` with control characters inside quotes or after a backslash replaced by private-use placeholders."""
    out, i = [], 0
    while i < len(command):
        quoted = command[i] in "'\"" or command[i] == "\\"
        end = _quote_end(command, i) if command[i] in "'\"" else i + 2 if quoted else i + 1
        out.append(command[i:end].translate(str.maketrans(MASKED)) if quoted else command[i])
        i = end
    return "".join(out)


def tokenize(command: str) -> list[str]:
    """Splits `command` into words and operator tokens (`&&`, `|`, `;`, `>`, ...) with POSIX quoting; `#` is not a comment. Raises ValueError on bad quoting."""
    lex = shlex.shlex(_mask_quoted(command), posix=True, punctuation_chars=True)
    lex.whitespace_split = True
    lex.commenters = ""
    return [Quoted(word.translate(str.maketrans(UNMASK))) if UNMASK.keys() & set(word) else word for word in lex]


def split_segments(tokens: list[str]) -> list[list[str]]:
    """Splits tokens into the commands between control operators (`&&`, `||`, `;`, `|`, `&`, `|&`, `;;`)."""
    segments: list[list[str]] = [[]]
    for token in tokens:
        if not isinstance(token, Quoted) and CONTROL_OPERATOR.fullmatch(token):
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
        elif command[i:i + 2] == "\\\n":
            i += 2
        elif char == "\\":
            current, i, word_start = current + command[i:i + 2], i + 2, False
        elif char == "\n":
            lines.append(current)
            current, i, word_start = "", i + 1, True
        elif char == "#" and word_start:
            i = command.find("\n", i) if "\n" in command[i:] else len(command)
        else:
            current, i, word_start = current + char, i + 1, char in " \t;|&()<>"
    return [*lines, current]
