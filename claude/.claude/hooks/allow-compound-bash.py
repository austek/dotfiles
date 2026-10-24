#!/usr/bin/env python3
import json
import os
import re
import shlex
import sys

SETTINGS_FILES = ("~/.claude/settings.json", ".claude/settings.json", ".claude/settings.local.json")
SEPARATORS = {"&&", "||", ";", "|"}
OPERATOR_CHARS = set("();<>|&")
SAFE_SINK = re.compile(r"^(/dev/null|/tmp/[^\s$`]*)$")
SENSITIVE = re.compile(r"\.ssh|\.aws|\.gnupg|\.kube|\.netrc|id_rsa|/etc/shadow")
ASSIGNMENT = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=")
UNSAFE_NAME = re.compile(r"^(PATH|IFS|SHELL|ENV|HOME|PROMPT_COMMAND|LD_.*|BASH_.*|GIT_.*|PYTHON.*|NODE_.*|_?JAVA.*)$")
LOOP_VAR = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
SAFE_COMMANDS = {
    "echo", "printf", "cat", "head", "tail", "wc", "cut", "tr", "sort", "basename",
    "dirname", "pwd", "ls", "true", "false", "sleep", "date", "diff", "test", "jq", "grep",
    "egrep", "fgrep", "stat", "readlink", "realpath", "seq", "pgrep",
}
UNSAFE_FLAGS = {"sort": re.compile(r"^(--output|--compress-program|-[^-]*o)"), "date": re.compile(r"^(--set|-[^-]*s)")}
EXEC_FLAGS = {"-exec", "-execdir", "-ok", "-okdir", "-delete"}


def load_rules(cwd):
    rules = {"allow": [], "deny": [], "ask": []}
    for path in SETTINGS_FILES:
        full = os.path.expanduser(path) if path.startswith("~") else os.path.join(cwd, path)
        try:
            with open(full, encoding="utf-8") as handle:
                permissions = json.load(handle).get("permissions", {})
        except (OSError, json.JSONDecodeError):
            continue
        for kind in rules:
            rules[kind] += [to_regex(e[5:-1]) for e in permissions.get(kind, []) if e.startswith("Bash(") and e.endswith(")")]
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


def starts_word(out):
    return not out or out[-1][-1:] in (" ", "\t", ";", "|", "&", "(")


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


def redirect_ok(op, target):
    if target is None:
        return False
    if op in (">", ">>", "&>", "&>>"):
        return bool(SAFE_SINK.match(target)) and ".." not in target
    if op == ">&":
        return target.isdigit() or target in ("-", "/dev/null")
    return op == "<" and not SENSITIVE.search(target)


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


def tokenize(command):
    lex = shlex.shlex(command, posix=True, punctuation_chars=True)
    lex.whitespace_split = True
    lex.commenters = ""
    return list(lex)


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


def has_unsafe_flag(words):
    pattern = UNSAFE_FLAGS.get(words[0])
    return bool(pattern) and any(pattern.match(w) for w in words[1:])


def runs_inner_command(words):
    return words[0] == "xargs" or (words[0] == "find" and bool(EXEC_FLAGS & set(words[1:])))


def command_allowed(words, rules):
    text = join_words(words)
    if SENSITIVE.search(text) or words[0].startswith("$"):
        return False
    if matches(text, rules["deny"]) or matches(text, rules["ask"]):
        return False
    if words[0] in SAFE_COMMANDS:
        return not has_unsafe_flag(words)
    return not runs_inner_command(words) and matches(text, rules["allow"])


def segment_allowed(words, rules):
    if not words or ASSIGNMENT.match(words[0]):
        return not words or strip_assignments(words) is not None
    if words[0] == "do":
        return segment_allowed(words[1:], rules)
    if words[0] == "done":
        return len(words) == 1
    if words[0] == "for":
        return len(words) >= 3 and words[2] == "in" and bool(LOOP_VAR.match(words[1]))
    return command_allowed(words, rules)


def analyze(command, rules, depth=0):
    extracted = extract_substitutions(command) if depth < 4 else None
    if extracted is None:
        return False
    stripped, inner = extracted
    if not all(analyze(c, rules, depth + 1) for c in inner):
        return False
    try:
        segments = build_segments(tokenize(stripped))
    except ValueError:
        return False
    return segments is not None and all(segment_allowed(s, rules) for s in segments)


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
    command = (data.get("tool_input") or {}).get("command")
    if data.get("tool_name") != "Bash" or not isinstance(command, str):
        return 0
    if any(marker in command for marker in ("`", "<<", "<(", ">(")):
        return 0
    rules = load_rules(data.get("cwd") or os.getcwd())
    if analyze(command, rules):
        print(allow_decision())
    return 0


if __name__ == "__main__":
    sys.exit(main())
