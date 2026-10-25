#!/usr/bin/env python3
"""Strip narrative comments from source files.

Exact for Python (uses `tokenize`, so strings/docstrings are never touched).
C-style and hash-style languages use a regex tokenizer that matches strings
before comments, so comment markers inside strings are left alone. Directive
comments (noqa, nolint, go:build, @ts-ignore, eslint-*) are kept. Unknown
extensions pass through unchanged.
"""
import argparse
import io
import re
import sys
import tokenize

C_STYLE_EXTS = {
    "c", "h", "cpp", "cc", "cxx", "hpp", "java", "js", "jsx", "ts", "tsx",
    "go", "kt", "kts", "scala", "rs", "swift", "cs", "php",
}
HASH_STYLE_EXTS = {"sh", "bash", "zsh", "yaml", "yml", "rb", "pl", "toml"}
QUOTE_STRING_EXTS = {"js", "jsx", "ts", "tsx", "php"}

_TRAILING_WS = re.compile(r"[ \t]+(?=\n)")
_DIRECTIVE = re.compile(
    r"^(?:#|//)\s*(?:noqa|type:|pragma|pylint:|fmt:|isort:|-\*-|(?:vim?|coding)[:=]"
    r"|nolint|go:|@ts-|eslint-|prettier-ignore|nosec|shellcheck)"
)

_DOUBLE = r'"(?:\\.|[^"\\])*"'
_TRIPLE = r'"""[\s\S]*?"""'
_BACKTICK = r"`(?:\\.|[^`\\])*`"
_SINGLE_LINE_STR = r"'(?:\\.|[^'\\\r\n])*'"
_SINGLE_CHAR = r"'(?:\\[^'\r\n]*|[^'\\\r\n])'"
_LINE = r"(?P<line>//[^\r\n]*)"
_BLOCK = r"(?P<block>/\*[\s\S]*?(?:\*/|\Z))"


def _c_style_pattern(ext: str) -> re.Pattern[str]:
    single = _SINGLE_LINE_STR if ext in QUOTE_STRING_EXTS else _SINGLE_CHAR
    return re.compile(f"(?P<str>{_TRIPLE}|{_DOUBLE}|{_BACKTICK}|{single})|{_LINE}|{_BLOCK}")


def _replace_c_comment(m: re.Match[str]) -> str:
    if m.group("str"):
        return m.group("str")
    if m.group("line"):
        return m.group("line") if _DIRECTIVE.match(m.group("line")) else ""
    return " " + "".join(re.findall(r"\r\n|\n|\r", m.group("block")))


def strip_c_style_comments(source: str, ext: str = "js") -> str:
    return _c_style_pattern(ext).sub(_replace_c_comment, source)


_HASH = re.compile(
    r"""(?P<str>\$'(?:\\.|[^'\\])*'|"(?:\\.|[^"\\])*"|'[^']*'|\\[\s\S])"""
    r"""|(?<![^ \t\r\n;])(?P<comment>\#[^\r\n]*)"""
)


def _replace_hash_comment(m: re.Match[str]) -> str:
    if m.group("str"):
        return m.group("str")
    return m.group("comment") if _DIRECTIVE.match(m.group("comment")) else ""


def _split_shebang(source: str) -> tuple[str, str]:
    if not source.startswith("#!"):
        return "", source
    newline = source.find("\n")
    if newline == -1:
        return source, ""
    return source[: newline + 1], source[newline + 1 :]


def strip_hash_comments(source: str) -> str:
    shebang, body = _split_shebang(source)
    return shebang + _HASH.sub(_replace_hash_comment, body)


def _is_shebang_token(tok: tokenize.TokenInfo) -> bool:
    row, col = tok.start
    return row == 1 and col == 0 and tok.string.startswith("#!")


def _keep_python_comment(tok: tokenize.TokenInfo) -> bool:
    return tok.type != tokenize.COMMENT or _is_shebang_token(tok) or bool(_DIRECTIVE.match(tok.string))


def strip_python_comments(source: str) -> str:
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(source).readline))
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return source
    kept = [tok for tok in tokens if _keep_python_comment(tok)]
    try:
        result = tokenize.untokenize(kept)
    except ValueError:
        return source
    return _TRAILING_WS.sub("", result)


def strip_comments(source: str, ext: str) -> str:
    ext = ext.lower().lstrip(".")
    if ext == "py":
        return strip_python_comments(source)
    if ext in C_STYLE_EXTS:
        return strip_c_style_comments(source, ext)
    if ext in HASH_STYLE_EXTS:
        return strip_hash_comments(source)
    return source


def _ext_of(path: str) -> str:
    return path.rsplit(".", 1)[-1] if "." in path else ""


def _strip_file(path: str) -> int:
    try:
        with open(path, "r", encoding="utf-8", newline="") as f:
            source = f.read()
        stripped = strip_comments(source, _ext_of(path))
        if stripped != source:
            with open(path, "w", encoding="utf-8", newline="") as f:
                f.write(stripped)
    except (OSError, UnicodeDecodeError) as e:
        print(f"strip_comments: {path}: {e}", file=sys.stderr)
        return 1
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("files", nargs="*", help="files to strip in place")
    parser.add_argument("--stdin", action="store_true", help="read source from stdin, write to stdout")
    parser.add_argument("--filename", default="", help="filename used to infer language when using --stdin")
    args = parser.parse_args()
    if args.stdin:
        sys.stdout.write(strip_comments(sys.stdin.read(), _ext_of(args.filename)))
        return 0
    return max((_strip_file(path) for path in args.files), default=0)


if __name__ == "__main__":
    sys.exit(main())
