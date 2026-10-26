#!/usr/bin/env python3
from __future__ import annotations

import itertools
import json
import posixpath
import re
import shlex
import sys

SEPARATORS = {"&&", "||", ";", "|"}

# Any tool that takes a shell command; the IDE terminal bypasses a Bash-only matcher.
GUARDED_TOOLS = {
    "Bash",
    "mcp__idea__execute_terminal_command",
    "mcp__idea__execute_tool",
    "mcp__idea__execute_run_configuration",
}

# execute_run_configuration carries no `command`; its overrides are the only shell text visible.
COMMAND_FIELDS = ("command", "programArguments")

# Targets considered catastrophic: filesystem root, home shorthand/env var,
# and other top-level system directories with no further sub-path given.
RISKY_TARGET = re.compile(
    r"^(?:"
    r"/\*?"
    r"|~/?\*?"
    r"|\$HOME/?\*?"
    r"|\$\{HOME\}/?\*?"
    r"|/root/?\*?"
    r"|/home/?\*?"
    r"|/(?:etc|usr|bin|sbin|boot|var|lib|lib64|opt|srv|mnt|run|snap|System|Library|Applications|Users|proc|sys|dev)/?\*?"
    r"|/home/[^/]+/?\*?"
    r"|/[^/]*[*?\[{][^/]*/?"
    r"|(?:\.\./?)+\*?"
    r"|\."
    r")$"
)

SAFE_VAR_PREFIX = re.compile(r"^\$(?:\{TMPDIR\}|TMPDIR)/(?!.*\.\.)[^$`]+$")
FIND_EXEC = {"-exec", "-execdir", "-ok", "-okdir"}
FIND_GLOBAL_OPTS = {"-H", "-L", "-P"}
SHELL_WRAPPERS = {"bash", "sh", "zsh", "dash", "ksh", "eval", "ssh"}
RM_WORD = re.compile(r"\brm\b")

# Bare variable/parameter expansion (e.g. $VAR, ${VAR}) — its value is unknown
# at hook time; if empty or unexpected, `rm -rf "$VAR"/*` can delete anything.
BARE_VAR = re.compile(
    r"^\$\{[^}]+\}/?\*?$"          # ${VAR}, ${VAR:-x}, ${VAR}/, ${VAR}/*
    r"|^\$[A-Za-z_][A-Za-z0-9_]*(?:/\$[A-Za-z_][A-Za-z0-9_]*)*/?\*?$"  # $VAR, $A/$B, $VAR/*
    r"|^\$[0-9@*#?$!-]/?\*?$"      # $1, $@, $*, $#, $?, $$, $!, $-
)


def tokenize(command: str) -> list[str]:
    # punctuation_chars=True keeps shell operators separate while still
    # respecting quoting, so text inside a quoted value is never split
    # into separate tokens.
    lex = shlex.shlex(command, posix=True, punctuation_chars=True)
    lex.whitespace_split = True
    lex.commenters = ""
    return list(lex)


def normalize(tok: str) -> str:
    return posixpath.normpath(re.sub(r"/{2,}", "/", tok))


def split_segments(tokens):
    segments = [[]]
    for tok in tokens:
        if tok in SEPARATORS:
            segments.append([])
        else:
            segments[-1].append(tok)
    return segments


def _is_rm(tok):
    return posixpath.basename(tok) == "rm"


def is_force_recursive(tokens: list[str]) -> bool:
    if not any(_is_rm(tok) for tok in tokens):
        return False
    flag_chars = set()
    for tok in tokens:
        if len(tok) > 2 and "--recursive".startswith(tok):
            flag_chars.add("r")
        elif len(tok) > 2 and "--force".startswith(tok):
            flag_chars.add("f")
        elif tok.startswith("--"):
            continue
        elif tok.startswith("-") and len(tok) > 1:
            flag_chars.update(tok[1:].lower())
    return "r" in flag_chars and "f" in flag_chars


def deny(seg_tokens: list[str], tok: str, reason: str) -> str:
    return json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": (
                "Blocked by block-dangerous-rm safety hook: "
                f"'{' '.join(seg_tokens)}' is a recursive force-delete "
                f"{reason} ('{tok}'). This is blocked regardless of "
                "permission mode (including auto/bypassPermissions). If "
                "this is genuinely intended, run it manually outside "
                "Claude Code."
            ),
        }
    })


def check_target(seg: list[str], tok: str) -> str | None:
    if BARE_VAR.match(tok):
        return deny(
            seg, tok,
            "targeting a bare variable with no literal path scope. "
            "Its resolved value is unknown at hook time — if it's "
            "empty or unset, this can delete far more than intended "
            "(the classic `rm -rf \"$VAR\"/*` footgun)",
        )
    if re.search(r"[$`]", tok) and not SAFE_VAR_PREFIX.match(tok):
        return deny(seg, tok, "targeting a non-literal path (expansion unknown at hook time)")
    if RISKY_TARGET.match(normalize(tok)):
        return deny(seg, tok, "targeting a high-risk path")
    return None


def has_substitution(seg: list[str]) -> bool:
    pairs = itertools.pairwise(seg)
    return any("`" in t for t in seg) or any(a.endswith("$") and b == "(" for a, b in pairs)


def check_segment(seg: list[str]) -> str | None:
    if any(posixpath.basename(t) in SHELL_WRAPPERS for t in seg):
        for tok in seg:
            verdict = check(tok) if re.search(r"\s", tok) else None
            if verdict:
                return verdict
    if not is_force_recursive(seg):
        return None
    if has_substitution(seg) or any(posixpath.basename(t) == "xargs" for t in seg):
        return deny(seg, "", "whose targets come from a substitution or xargs")
    targets = [t for t in seg if t and not t.startswith("-")]
    targets = [t for t in targets if t not in ("sudo", "rtk") and not _is_rm(t)]
    return next((v for v in (check_target(seg, t) for t in targets) if v), None)


def extract_exec(tokens: list[str]) -> tuple[list[str], list[list[str]]]:
    outer, inners, current = [], [], None
    for tok in tokens:
        if current is not None and tok in (";", "+"):
            inners.append(current)
            current = None
        elif current is not None:
            current.append(tok)
        else:
            outer.append(tok)
            current = [] if tok in FIND_EXEC else None
    return outer, inners + ([current] if current else [])


def _skip_find_options(args: list[str]) -> list[str]:
    i = 0
    while i < len(args):
        if args[i] == "-D":
            i += 2
        elif args[i] in FIND_GLOBAL_OPTS or re.fullmatch(r"-O\d?", args[i]):
            i += 1
        else:
            break
    return args[i:]


def find_start_paths(seg: list[str]) -> list[str]:
    idx = next((i for i, t in enumerate(seg) if posixpath.basename(t) == "find"), None)
    if idx is None:
        return []
    rest = _skip_find_options(seg[idx + 1:])
    return list(itertools.takewhile(lambda t: not t.startswith(("-", "!", "(")), rest))


def check_find_paths(segments: list[list[str]], inners: list[list[str]]) -> str | None:
    destructive = any(is_force_recursive(i) for i in inners) or any("-delete" in s for s in segments)
    if not destructive:
        return None
    for seg in segments:
        verdict = next((v for t in find_start_paths(seg) if t != "." and (v := check_target(seg, t))), None)
        if verdict:
            return verdict
    return None


def check(command: str) -> str | None:
    try:
        tokens = tokenize(command)
    except ValueError:
        return deny([command], "", "in an unparseable command") if RM_WORD.search(command) else None
    outer, inners = extract_exec(tokens)
    segments = split_segments(outer)
    verdicts = map(check_segment, segments + inners)
    return next((v for v in verdicts if v), None) or check_find_paths(segments, inners)


def main():
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return 0

    if data.get("tool_name") not in GUARDED_TOOLS:
        return 0

    tool_input = data.get("tool_input") or {}

    for field in COMMAND_FIELDS:
        value = tool_input.get(field)
        if not isinstance(value, str) or not value:
            continue
        verdict = check(value)
        if verdict:
            print(verdict)
            return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
