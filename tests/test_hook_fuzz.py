"""Seeded fuzzing of the hooks' shared tokenizer and the compound-command gate against bash and zsh."""
import random
import re
import shlex
import shutil
import subprocess
from functools import cache

import pytest
from hook_support import RULES, hook, load_hook

rm_hook = load_hook("block-dangerous-rm.py")
SEEDS = (1, 7, 42, 2024, 31337, 99991)
CASES_PER_SEED = 1000
WORDS = ("echo", "ls", "cat", "grep", "jq", "git", "find")
PLAIN = ("a", "-l", "-n", "foo.txt", "x/y", "status", "--", "1", "'.a'", ".", "log", "-name")
SEPARATORS = (" ; ", " && ", " || ", " | ", " & ", "\n", " ;\n", "\n\n", " |& ")
ADVERSARIAL = (
    "'a b'", '"a b"', "'", '"', "\\", "\\'", '\\"', "\\;", "\\|", "$'a\\nb'", '$"x"', "${x@Q}", "${x:-y}",
    "{a,b}", "{1..3}", "$(ls)", "`ls`", "<(ls)", ">(cat)", "<<EOF", "<<-X", "# c", "a#b", "> /tmp/o",
    ">/dev/null", "2>&1", "> ~/o", "< /dev/null", "~", "~/x", "*", "?", "[a-z]*", "é", "\x07", "\r", "\t",
    "\u2028", "$((1+2))", "$(", ")", "(", "$x", "${x}", '"$(ls "a")"', "$(echo $(ls))", "'$(ls)'", '"{a,b}"',
    "'\\'", "\"'\"", "$'\\''", "\\\n", "&>/dev/null", ">>/tmp/o", "=====", "{", "}", "!", "[[", "$[1]",
    "<<<x", ">|/tmp/o", "<&3", "1>&2", ";;", "&&&", "$0", "$@", "{a,b}c", "a{,}", "x{1..3}y", "{a..c}", "{,}",
    "${x//a/b}", "${!x}", "${x[@]}", "=(ls)", "=ls", "*(.)", "**/*", "^x", "$'\\x41'", "$[ 1 ]", "!!", "{a,{b,c}}",
    "${(f)x}", "$(<f)", "~root", "~+", "a\\ b", "'a'\"b\"", "\\$(ls)", "\"\\$(ls)\"", "'\"'", "\"'\"'\"'",
)
MUTATION_CHARS = "'\"\\$(){}`;&|<>#~*\n"


def atom(rng, depth):
    if depth > 0 and rng.random() < 0.15:
        wrap = rng.choice(("$(%s)", '"$(%s)"', "'%s'", '"%s"', "<(%s)", "`%s`"))
        return wrap % command(rng, depth - 1)
    return rng.choice(ADVERSARIAL if rng.random() < 0.4 else PLAIN)


def simple(rng, depth):
    args = [atom(rng, depth) for _ in range(rng.randint(0, 4))]
    return " ".join([rng.choice(WORDS), *args])


def command(rng, depth=2):
    text = simple(rng, depth)
    for _ in range(rng.randint(0, 3)):
        text += rng.choice(SEPARATORS) + simple(rng, depth)
    return text


def mutate(rng, text):
    if text and rng.random() < 0.3:
        i = rng.randrange(len(text))
        return text[:i] + rng.choice(MUTATION_CHARS) + text[i + rng.choice((0, 1)):]
    return text


def corpus(seed):
    rng = random.Random(seed)
    return list(dict.fromkeys(mutate(rng, command(rng)) for _ in range(CASES_PER_SEED)))


def strict_parse(parser, text):
    executable = shutil.which(parser[0]) or parser[0]
    try:
        done = subprocess.run([executable, *parser[1:], text], capture_output=True, timeout=2, check=False, env={"PATH": "/usr/bin:/bin"})
    except ValueError:
        return False
    errors = done.stderr.decode(errors="replace").splitlines()
    return done.returncode == 0 or bool(errors) and all(line.endswith("not found") for line in errors)


@cache
def gate(text):
    return hook.should_allow(text, RULES)


def allowed(seed):
    return [c for c in corpus(seed) if gate(c)]


@pytest.mark.parametrize("seed", SEEDS)
def test_p1_every_allowed_command_parses_strictly_in_bash_and_zsh(seed):
    for text in allowed(seed):
        assert strict_parse(("bash", "-n", "-c"), text), f"bash -n rejects an allowed command: {text!r}"
        assert strict_parse(("zsh", "-f", "-n", "-c"), text), f"zsh -n rejects an allowed command: {text!r}"


BASH_ORACLE = r"""
while IFS= read -r -d '' c; do
  unset -f f
  if eval "f() { $c"$'\n}' 2>/dev/null; then declare -f f; else echo ERR; fi
  printf '\0'
done
"""
OPERATOR_SPLIT = re.compile(r"\|&|\|\||&&|[|;&]|\n")
REDIRECT = re.compile(r"^\d*(?:>>|>&|>|<|&>>|&>)")


def normalized_bodies(commands):
    """`declare -f` output of each command wrapped in a bash function, which prints one statement per line."""
    payload = ("\0".join(commands) + "\0").encode()
    done = subprocess.run(["bash", "-c", BASH_ORACLE], input=payload, capture_output=True, check=True, timeout=120)
    return [chunk.rstrip("\n").split("\n") for chunk in done.stdout.decode().split("\0")[:-1]]


def split_top_level(line):
    pieces, current, quote, i = [], "", None, 0
    while i < len(line):
        ch = line[i]
        if ch == "\\" and quote != "'":
            current, i = current + line[i:i + 2], i + 2
        elif quote or ch in "'\"":
            quote = None if ch == quote else quote or ch
            current, i = current + ch, i + 1
        elif REDIRECT.match(line[i:]) and (not current or current[-1] == " "):
            width = len(REDIRECT.match(line[i:]).group())
            current, i = current + line[i:i + width], i + width
        elif m := OPERATOR_SPLIT.match(line, i):
            pieces, current, i = [*pieces, current], "", m.end()
        else:
            current, i = current + ch, i + 1
    return [*pieces, current]


def first_word(words):
    words = list(words)
    while words and (hook.ASSIGNMENT.match(words[0]) or words[0] in ("do", "!", "time")):
        words.pop(0)
    while words and REDIRECT.match(words[0]):
        words = words[2:] if REDIRECT.fullmatch(words[0]) else words[1:]
    return words[0] if words and words[0] not in ("done", "for") else None


def bash_firsts(body):
    pieces = split_top_level("\n".join(body[2:-1]))
    return [w for p in pieces if (w := first_word(shlex.split(p))) is not None]


def hook_firsts(text):
    stripped = hook.extract_substitutions(text)[0]
    segments = hook.build_segments(hook.tokenize(stripped))
    return [w for s in segments if (w := first_word(s)) is not None]


def plain_allowed(seed):
    return [c for c in allowed(seed) if "$(" not in c and "\x00" not in c and "\\\n" not in c]


@pytest.mark.parametrize("seed", SEEDS)
def test_p2_hook_segments_agree_with_bash_declare_f(seed):
    # Oracle limits: bash's normalized text is re-split by split_top_level (quote-aware), and commands with
    # $(..) or a line continuation are skipped; only the first word of each simple command is compared.
    commands = plain_allowed(seed)
    for text, body in zip(commands, normalized_bodies(commands), strict=True):
        if body == ["ERR"]:
            assert not hook_firsts(text), f"bash cannot define a function from an allowed command: {text!r}"
            continue
        assert hook_firsts(text) == bash_firsts(body), f"segment disagreement for {text!r}: bash body {body!r}"


def unmodeled_unquoted(text):
    """Independent scan for constructs the gate does not model, outside single quotes (outside all quotes for some)."""
    quote, i, hits = None, 0, []
    while i < len(text):
        ch, rest = text[i], text[i:]
        if ch == "\\" and quote != "'":
            i += 2
            continue
        if ch == "#" and quote is None and (i == 0 or text[i - 1] in " \t\n;|&("):
            i = text.find("\n", i) if "\n" in rest else len(text)
            continue
        if quote is None and rest.startswith(("$'", '$"', "<(", ">(")):
            hits.append(rest[:2])
        if quote is None and re.match(r"\{[^{}\s]*(,|\.\.)[^{}\s]*\}", rest):
            hits.append("brace")
        if quote != "'" and (ch == "`" or re.match(r"\$\{[^}]*@", rest)):
            hits.append(ch)
        quote = None if ch == quote else quote or (ch if ch in "'\"" else None)
        i += 1
    return hits or (["unbalanced quote"] if quote else [])


@pytest.mark.parametrize("seed", SEEDS)
def test_p3_unmodeled_expansions_are_never_allowed(seed):
    # The scanner has no context stack, so commands nesting quotes inside $(..) are left to P1 and P2.
    for text in (c for c in corpus(seed) if "$(" not in c):
        hits = unmodeled_unquoted(text)
        assert not (hits and gate(text)), f"allowed despite {hits}: {text!r}"


FLAGS = ("-rf", "-fr", "-r -f", "-f -r", "-Rf", "-rfv", "--recursive --force", "--force --recursive", "-r --force", "--recurs -f")
RMS = ("rm", "\\rm", "/bin/rm", "sudo rm", "command rm", "r''m", '"rm"', "env FOO=1 rm", "nice rm")
PROTECTED = (
    "~", "~/", "~/.ssh", "~/.ssh/", "~/.config", "~/Workspace", "~/.dotfiles", '"$HOME"', '"$HOME"/.config', "$HOME",
    "${HOME}/Workspace", '"${HOME}/.aws"', "/", "/*", "/etc", "/home/user", "/home/user/.gnupg", "~/*", "$HOME/*",
)
HARMLESS = ("./build", "/tmp/x", "/tmp/x/y", "build/out", '"/tmp/a b"', "target", "node_modules", "$TMPDIR/x", "/tmp/x/")
PRELUDES = ("", "cd /tmp && ", "echo x; ", "true | ", "echo x\n", "ls || ", "echo hi > /dev/null; ")


def rm_line(rng, targets):
    flags, rm = rng.choice(FLAGS), rng.choice(RMS)
    words = flags.split()
    rng.shuffle(words)
    words.insert(rng.randint(0, len(words)), rng.choice(targets))
    return rng.choice(PRELUDES) + f"{rm} {' '.join(words)}"


@pytest.mark.parametrize(
    "line", ["rm ~/.ssh -rf", "rm -r ~/.ssh -f", "rm ~/Workspace --recursive --force", "rm -f ~/.config -r"]
)
def test_p4_flags_after_or_around_a_protected_target_are_denied(line):
    assert rm_hook.guarded_check(line), f"rm hook is silent on {line!r}"


@pytest.mark.parametrize("line", ["rm ./build -rf", "rm -r /tmp/x -f"])
def test_p4_flags_after_or_around_a_harmless_target_stay_silent(line):
    assert rm_hook.guarded_check(line) is None, f"rm hook denies harmless {line!r}"


@pytest.mark.parametrize("seed", SEEDS)
def test_p4_rm_hook_denies_protected_targets_and_ignores_harmless_ones(seed):
    rng = random.Random(seed)
    for _ in range(120):
        risky, harmless = rm_line(rng, PROTECTED), rm_line(rng, HARMLESS)
        assert rm_hook.guarded_check(risky), f"rm hook is silent on {risky!r}"
        assert rm_hook.guarded_check(harmless) is None, f"rm hook denies harmless {harmless!r}"
