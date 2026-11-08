#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys

sys.dont_write_bytecode = True  # a __pycache__ here would land inside the stowed package
sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
from _shell import SEPARATORS, tokenize

SETTINGS_FILES = ("~/.claude/settings.json", ".claude/settings.json", ".claude/settings.local.json")
OPERATOR_CHARS = set("();<>|&")
SAFE_SINK = re.compile(r"^(/dev/null|/tmp/[^\s$`]*)$")
SENSITIVE = re.compile(
    r"\.ssh|\.aws|\.gnupg|\.kube|\.netrc|id_rsa|/etc/shadow|secrets\.env|\.credentials"
    r"|\.git-credentials|\.npmrc|gh/hosts\.yml|/proc/[^/]*/environ|/dev/(?:tcp|udp)/|\.env(?:\W|$)"
    r"|\.config/(?:gcloud|rclone)|\.(?:docker|azure)(?![\w.-])|\.pgpass|\.local/share/keyrings"
)
JQ_FILE_FLAG = re.compile(r"^(?:-[A-Za-z]*f[A-Za-z]*|--from-file|--rawfile|--slurpfile)$")
QUOTE_OR_BRACE_EXPANSION = re.compile(r"\$['\"]|\{[^{}\s]*(?:,|\.\.)[^{}\s]*\}|\\[|;&<>()]")
TRANSFORM_EXPANSION = re.compile(r"\$\{[^}]*[@\[]|\$\{\(|\$\[")
PARSERS = (("bash", "-n", "-c"), ("zsh", "-f", "-n", "-c"))
ASSIGNMENT = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=")
UNSAFE_NAME = re.compile(r"^(PATH|IFS|SHELL|ENV|HOME|PROMPT_COMMAND|LD_.*|BASH_.*|GIT_.*|PYTHON.*|NODE_.*|_?JAVA.*)$")
JQ_ENV = re.compile(r"\benv\b|\$ENV|\$__loc__|input_filename")
LOOP_VAR = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
SAFE_COMMANDS = {
    "echo", "printf", "cat", "head", "tail", "wc", "cut", "tr", "sort", "basename",
    "dirname", "pwd", "ls", "true", "false", "sleep", "date", "diff", "test", "jq", "grep",
    "egrep", "fgrep", "stat", "readlink", "realpath", "seq", "pgrep",
}
UNSAFE_FLAGS = {
    "sort": re.compile(r"^(--o|--c|-[^-]*o)"),
    "date": re.compile(r"^(--s|-[^-]*s)"),
    "printf": re.compile(r"^-v"),
}
EXEC_FLAGS = {"-exec", "-execdir", "-ok", "-okdir", "-delete", "-fprint", "-fprint0", "-fprintf", "-fls"}


class SettingsError(Exception):
    """A settings file exists but cannot be read as rules, so its deny and ask rules are unknown."""


def read_permissions(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as error:
        raise SettingsError(f"{path}: {error}") from error
    permissions = data.get("permissions", {}) if isinstance(data, dict) else None
    if not isinstance(permissions, dict):
        raise SettingsError(f"{path}: no permissions object")
    return permissions


def bash_rules(path: str, permissions: dict, kind: str) -> list:
    entries = permissions.get(kind, [])
    if not isinstance(entries, list) or not all(isinstance(e, str) for e in entries):
        raise SettingsError(f"{path}: permissions.{kind} is not a list of strings")
    return [to_regex(e[5:-1]) for e in entries if e.startswith("Bash(") and e.endswith(")")]


def load_rules(cwd):
    rules = {"allow": [], "deny": [], "ask": []}
    for path in SETTINGS_FILES:
        full = os.path.expanduser(path) if path.startswith("~") else os.path.join(cwd, path)
        permissions = read_permissions(full)
        for kind in rules:
            rules[kind] += bash_rules(full, permissions, kind)
    return rules


def to_regex(pattern):
    if pattern.endswith(":*"):
        return re.compile("^" + re.escape(pattern[:-2]) + r"(\s.*)?$", re.DOTALL)
    if pattern.endswith(" *"):
        return re.compile("^" + re.escape(pattern[:-2]).replace(r"\*", ".*") + r"(\s.*)?$", re.DOTALL)
    return re.compile("^" + re.escape(pattern).replace(r"\*", ".*") + "$", re.DOTALL)


def matches(text, patterns):
    return any(p.match(text) for p in patterns)


def matching_paren(command, start):
    depth, quote, i = 1, None, start
    while i < len(command):
        ch = command[i]
        if ch == "\\" and quote != "'":
            i += 1
        elif quote:
            quote = None if ch == quote else quote
        elif ch in "'\"":
            quote = ch
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return -1


def next_quote(quote, ch):
    if ch in "'\"" and quote in (None, ch):
        return None if quote else ch
    return quote


def starts_word(out: list[str]) -> bool:
    return not out or (not out[-1].startswith("\\") and out[-1][-1:] in (" ", "\t", ";", "|", "&", "("))


def extract_substitutions(command):
    out, inner, quote, i = [], [], None, 0
    while i < len(command):
        ch, pair = command[i], command[i:i + 2]
        if ch == "\\" and quote != "'":
            out.append("" if pair == "\\\n" else pair)
            i += 2
        elif quote != "'" and command.startswith("$(", i):
            end = matching_paren(command, i + 2)
            if end < 0 or command.startswith("$((", i):
                return None
            inner.append(command[i + 2:end])
            out.append("SUBST")
            i = end + 1
        elif ch == "#" and quote is None and starts_word(out):
            i = command.find("\n", i) if "\n" in command[i:] else len(command)
        else:
            quote = next_quote(quote, ch)
            out.append(" ; " if ch == "\n" and quote is None else ch)
            i += 1
    return "".join(out), inner


def sensitive_path(path: str) -> bool:
    """True when `path`, as written or after resolving `~`, `..` and symlinks, names a secret; unresolvable counts."""
    try:
        resolved = os.path.realpath(os.path.expanduser(path))
    except ValueError:
        return True
    return bool(SENSITIVE.search(path) or SENSITIVE.search(resolved))


def redirect_ok(op, target):
    if target is None:
        return False
    if op in (">", ">>", "&>", "&>>"):
        return bool(SAFE_SINK.match(target)) and ".." not in target
    if op == ">&":
        return target.isdigit() or target in ("-", "/dev/null")
    return op == "<" and not sensitive_path(target)


def build_segments(tokens):
    segments, current, i = [], [], 0
    while i < len(tokens):
        tok = tokens[i]
        if tok in SEPARATORS:
            segments.append(current)
            current = []
        elif set(tok) <= OPERATOR_CHARS:
            if not redirect_ok(tok, tokens[i + 1] if i + 1 < len(tokens) else None):
                return None
            if current and current[-1].isdigit():
                current.pop()
            i += 1
        else:
            current.append(tok)
        i += 1
    return segments + [current]


def strip_assignments(words):
    i = 0
    while i < len(words) and ASSIGNMENT.match(words[i]):
        name = ASSIGNMENT.match(words[i]).group(1)
        if UNSAFE_NAME.match(name) or name in os.environ:
            return None
        i += 1
    return words[i:] if i == len(words) else None


def join_words(words):
    return " ".join(shlex.quote(w) if not w or re.search(r"\s", w) else w for w in words)


def expands(word: str) -> bool:
    return "$" in word or "SUBST" in word


def has_unsafe_flag(words: list[str]) -> bool:
    if words[0] == "jq" and any(JQ_ENV.search(w) or JQ_FILE_FLAG.match(w) for w in words[1:]):
        return True
    pattern = UNSAFE_FLAGS.get(words[0])
    if pattern and any(expands(w) for w in words[1:]):
        return True
    return bool(pattern) and any(pattern.match(w) for w in words[1:])


def runs_inner_command(words: list[str]) -> bool:
    if words[0] == "find" and any(expands(w) for w in words[1:]):
        return True
    return words[0] == "xargs" or (words[0] == "find" and bool(EXEC_FLAGS & set(words[1:])))


GLOB_CHARS = re.compile(r"[*?\[{]")
FILE_ARG_COMMANDS = {"cat", "head", "tail", "wc", "ls", "stat", "readlink", "realpath", "diff", "sort", "cut"}


def globbed_path(word: str, command: str) -> bool:
    if not GLOB_CHARS.search(word):
        return False
    return command in FILE_ARG_COMMANDS or "/" in word or word.startswith("~")


PATTERN_COMMANDS = {"grep", "egrep", "fgrep", "jq"}


def has_globbed_path(words: list[str]) -> bool:
    pattern_pending = words[0] in PATTERN_COMMANDS
    for word in words[1:]:
        is_flag = word.startswith("-")
        command = "cat" if words[0] in PATTERN_COMMANDS and not is_flag and not pattern_pending else words[0]
        pattern_pending = pattern_pending and is_flag
        if globbed_path(word, command):
            return True
    return False


GRADLE_TASK = re.compile(r"^(:[\w.-]+)*:?(spotlessApply|spotlessCheck|test|integrationTest|check|compileJava|compileTestJava)$")
GRADLE_FLAG = re.compile(r"^(-D[\w.]+=[\w.,:/-]+|--no-daemon|--offline|--continue|--rerun-tasks|--console=plain|-q|-i|--info|--stacktrace)$")


def gradle_allowed(words: list[str]) -> bool:
    args, tasks = iter(words[1:]), 0
    for arg in args:
        if arg == "--tests":
            value = next(args, "-")
            if value.startswith("-") or expands(value):
                return False
        elif GRADLE_TASK.match(arg):
            tasks += 1
        elif not GRADLE_FLAG.match(arg):
            return False
    return tasks > 0


def attached_values(flag: str) -> list[str]:
    """The text a flag may carry as its file operand: `--file=PATH` gives PATH, `-fPATH` gives every suffix after `-f`."""
    value = flag.partition("=")[2]
    return [value] if value else [flag[i:] for i in range(2, len(flag))]


def path_operands(args: list[str]) -> list[str]:
    """Non-flag words, every word after `--`, and the values attached to flags."""
    operands, after_dashes = [], False
    for word in args:
        if after_dashes or not word.startswith("-"):
            operands.append(word)
        elif word == "--":
            after_dashes = True
        else:
            operands += attached_values(word)
    return operands


def names_secret(words: list[str]) -> bool:
    """True when the command text, or any operand resolved against the working directory, names a secret."""
    return bool(SENSITIVE.search(join_words(words))) or any(sensitive_path(w) for w in path_operands(words[1:]))


def command_allowed(words: list[str], rules: dict) -> bool:
    text = join_words(words)
    if names_secret(words) or words[0].startswith("$"):
        return False
    if matches(text, rules["deny"]) or matches(text, rules["ask"]):
        return False
    if words[0] in ("./gradlew", "gradlew"):
        return gradle_allowed(words)
    if words[0] in SAFE_COMMANDS:
        return not has_unsafe_flag(words) and not any("$" in w for w in words[1:]) and not has_globbed_path(words)
    return not runs_inner_command(words) and matches(text, rules["allow"])


def safe_loop_var(name: str) -> bool:
    return bool(LOOP_VAR.match(name)) and not UNSAFE_NAME.match(name) and name not in os.environ


def segment_allowed(words: list[str], rules: dict) -> bool:
    if not words or ASSIGNMENT.match(words[0]):
        return not words or strip_assignments(words) is not None
    if words[0] == "do":
        return segment_allowed(words[1:], rules)
    if words[0] == "done":
        return len(words) == 1
    if words[0] == "for":
        return len(words) >= 3 and words[2] == "in" and safe_loop_var(words[1])
    return command_allowed(words, rules)


def analyze(command, rules, depth=0):
    extracted = extract_substitutions(command) if depth < 4 else None
    if extracted is None:
        return False
    stripped, inner = extracted
    if unquoted_expansion(stripped) or not all(analyze(c, rules, depth + 1) for c in inner):
        return False
    try:
        segments = build_segments(tokenize(stripped))
    except ValueError:
        return False
    return segments is not None and all(segment_allowed(s, rules) for s in segments)


def quote_views(command: str) -> tuple[str, str]:
    """The text outside every quote (opening quotes kept) and the text outside single quotes."""
    outside, expandable, quote, i = [], [], None, 0
    while i < len(command):
        ch = command[i]
        if ch == "\\" and quote != "'":
            escaped = command[i + 1:i + 2]
            if quote is None and escaped and escaped in "|;&<>()":
                outside.append(ch + escaped)
            i += 2
            continue
        if quote is None and ch in "'\"":
            quote = ch
            outside.append(ch)
        elif quote == ch:
            quote = None
        else:
            if quote is None:
                outside.append(ch)
            if quote != "'":
                expandable.append(ch)
        i += 1
    return "".join(outside), "".join(expandable)


def unquoted_expansion(command: str) -> bool:
    """True for `$'..'`, `$".."`, `{a,b}`, `{a..b}` or an escaped operator such as `\\|` outside quotes, or `${x@op}`, `${(f)x}`, `${a[i]}`, `$[..]` outside single quotes."""
    outside, expandable = quote_views(command)
    return bool(QUOTE_OR_BRACE_EXPANSION.search(outside) or TRANSFORM_EXPANSION.search(expandable))


def parses_as(parser: tuple[str, ...], command: str) -> bool | None:
    """True when the parser's `-n` run accepts `command` (zsh's "not found" for `=====` is not a syntax error); None when not installed."""
    try:
        parsed = subprocess.run(
            [*parser, command], capture_output=True, timeout=2, check=False,
            env={"PATH": os.environ.get("PATH", "/usr/bin:/bin")},
        )
    except FileNotFoundError:
        return None
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return False
    errors = parsed.stderr.decode(errors="replace").splitlines()
    return parsed.returncode == 0 or bool(errors) and all(line.endswith("not found") for line in errors)


def parses_in_shells(command: str) -> bool:
    """True when bash accepts `command` and zsh, if installed, does too; the Bash tool runs either."""
    bash, zsh = (parses_as(parser, command) for parser in PARSERS)
    return bash is True and zsh is not False


def should_allow(command: str, rules: dict) -> bool:
    if any(marker in command for marker in ("`", "<<", "<(", ">(")):
        return False
    return analyze(command, rules) and parses_in_shells(command)


def allow_decision():
    return json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "allow",
            "permissionDecisionReason": "Every segment of the compound command matches the allowlist.",
        }
    })


def main():
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return 0
    if not isinstance(data, dict):
        return 0
    tool_input = data.get("tool_input")
    command = tool_input.get("command") if isinstance(tool_input, dict) else None
    if data.get("tool_name") != "Bash" or not isinstance(command, str):
        return 0
    cwd = data.get("cwd") if isinstance(data.get("cwd"), str) else os.getcwd()
    try:
        os.chdir(cwd)
        rules = load_rules(cwd)
    except (OSError, SettingsError) as error:
        print(f"allow-compound-bash: no decision, {error}", file=sys.stderr)
        return 0
    if should_allow(command, rules):
        print(allow_decision())
    return 0


if __name__ == "__main__":
    sys.exit(main())
