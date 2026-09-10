#!/usr/bin/env python3
import json
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
    r"|/(?:etc|usr|bin|boot|var|lib|lib64|opt|System|Library|Applications|Users|proc|sys|dev)/?\*?"
    r"|\.\./?\*?"
    r")$"
)

SCRATCH_OK = re.compile(r"(?:^|/)(?:tmp|var/tmp)(?:/|$)|\$TMPDIR|scratchpad")

# Bare variable/parameter expansion (e.g. $VAR, ${VAR}) — its value is unknown
# at hook time; if empty or unexpected, `rm -rf "$VAR"/*` can delete anything.
BARE_VAR = re.compile(
    r"^\$\{[^}]+\}/?\*?$"          # ${VAR}, ${VAR:-x}, ${VAR}/, ${VAR}/*
    r"|^\$[A-Za-z_][A-Za-z0-9_]*/?\*?$"  # $VAR, $VAR/, $VAR/*
    r"|^\$[0-9@*#?$!-]/?\*?$"      # $1, $@, $*, $#, $?, $$, $!, $-
)


def tokenize(command):
    # punctuation_chars=True keeps shell operators separate while still
    # respecting quoting, so text inside a quoted value is never split
    # into separate tokens.
    lex = shlex.shlex(command, posix=True, punctuation_chars=True)
    lex.whitespace_split = True
    return list(lex)


def split_segments(tokens):
    segments = [[]]
    for tok in tokens:
        if tok in SEPARATORS:
            segments.append([])
        else:
            segments[-1].append(tok)
    return segments


def is_force_recursive(tokens):
    if "rm" not in tokens:
        return False
    flag_chars = set()
    for tok in tokens:
        if tok == "--recursive":
            flag_chars.add("r")
        elif tok == "--force":
            flag_chars.add("f")
        elif tok.startswith("--"):
            continue
        elif tok.startswith("-") and len(tok) > 1:
            flag_chars.update(tok[1:].lower())
    return "r" in flag_chars and "f" in flag_chars


def deny(seg_tokens, tok, reason):
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


def check(command):
    try:
        tokens = tokenize(command)
    except ValueError:
        # Unbalanced quotes etc. — can't safely analyze, so don't block.
        return None

    for seg in split_segments(tokens):
        if not is_force_recursive(seg):
            continue

        targets = [t for t in seg if t and not t.startswith("-")]
        targets = [t for t in targets if t not in ("rm", "sudo", "rtk")]

        for tok in targets:
            if BARE_VAR.match(tok):
                return deny(
                    seg, tok,
                    "targeting a bare variable with no literal path scope. "
                    "Its resolved value is unknown at hook time — if it's "
                    "empty or unset, this can delete far more than intended "
                    "(the classic `rm -rf \"$VAR\"/*` footgun)",
                )

            if RISKY_TARGET.match(tok) and not SCRATCH_OK.search(tok):
                return deny(seg, tok, "targeting a high-risk path")

    return None


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
