"""Shell tokenizing shared by the Claude Code hooks in this directory."""
from __future__ import annotations

import shlex

SEPARATORS = frozenset({"&&", "||", ";", "|"})


def tokenize(command: str) -> list[str]:
    """Splits `command` into words and operator tokens (`&&`, `|`, `;`, `>`, ...) with POSIX quoting; `#` is not a comment. Raises ValueError on bad quoting."""
    lex = shlex.shlex(command, posix=True, punctuation_chars=True)
    lex.whitespace_split = True
    lex.commenters = ""
    return list(lex)


def split_segments(tokens: list[str]) -> list[list[str]]:
    segments: list[list[str]] = [[]]
    for token in tokens:
        if token in SEPARATORS:
            segments.append([])
        else:
            segments[-1].append(token)
    return segments
