#!/usr/bin/env python3
"""Strip narrative comments from source files.

Exact for Python (uses `tokenize`, so strings/docstrings are never touched).
Best-effort char-scanner for C-style and hash-style languages: respects
quoted strings and backslash escapes, so comment markers inside strings are
left alone. Unknown extensions pass through unchanged.
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

_TRAILING_WS = re.compile(r"[ \t]+(?=\n)")


def _is_shebang_token(tok) -> bool:
    row, col = tok.start
    return row == 1 and col == 0 and tok.string.startswith("#!")


def strip_python_comments(source: str) -> str:
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(source).readline))
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return source
    kept = [tok for tok in tokens if tok.type != tokenize.COMMENT or _is_shebang_token(tok)]
    try:
        result = tokenize.untokenize(kept)
    except ValueError:
        return source
    return _TRAILING_WS.sub("", result)


def strip_c_style_comments(source: str) -> str:
    out = []
    i, n = 0, len(source)
    in_string = None
    while i < n:
        ch = source[i]
        nxt = source[i + 1] if i + 1 < n else ""
        if in_string:
            out.append(ch)
            if ch == "\\" and nxt:
                out.append(nxt)
                i += 2
                continue
            if ch == in_string:
                in_string = None
            i += 1
            continue
        if ch in ("'", '"', "`"):
            in_string = ch
            out.append(ch)
            i += 1
            continue
        if ch == "/" and nxt == "/":
            while i < n and source[i] != "\n":
                i += 1
            continue
        if ch == "/" and nxt == "*":
            i += 2
            out.append(" ")
            while i < n and not (source[i] == "*" and i + 1 < n and source[i + 1] == "/"):
                if source[i] == "\n":
                    out.append("\n")
                i += 1
            i += 2
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def strip_hash_comments(source: str) -> str:
    shebang, source = _split_shebang(source)
    return shebang + _strip_hash_comments_body(source)


def _split_shebang(source: str) -> tuple[str, str]:
    if not source.startswith("#!"):
        return "", source
    newline = source.find("\n")
    if newline == -1:
        return source, ""
    return source[: newline + 1], source[newline + 1 :]


def _strip_hash_comments_body(source: str) -> str:
    out = []
    i, n = 0, len(source)
    in_string = None
    while i < n:
        ch = source[i]
        nxt = source[i + 1] if i + 1 < n else ""
        if in_string:
            out.append(ch)
            if in_string == '"' and ch == "\\" and nxt:
                out.append(nxt)
                i += 2
                continue
            if ch == in_string:
                in_string = None
            i += 1
            continue
        if ch in ("'", '"'):
            in_string = ch
            out.append(ch)
            i += 1
            continue
        if ch == "#":
            while i < n and source[i] != "\n":
                i += 1
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def strip_comments(source: str, ext: str) -> str:
    ext = ext.lower().lstrip(".")
    if ext == "py":
        return strip_python_comments(source)
    if ext in C_STYLE_EXTS:
        return strip_c_style_comments(source)
    if ext in HASH_STYLE_EXTS:
        return strip_hash_comments(source)
    return source


def _ext_of(path: str) -> str:
    return path.rsplit(".", 1)[-1] if "." in path else ""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("files", nargs="*", help="files to strip in place")
    parser.add_argument("--stdin", action="store_true", help="read source from stdin, write to stdout")
    parser.add_argument("--filename", default="", help="filename used to infer language when using --stdin")
    args = parser.parse_args()

    if args.stdin:
        source = sys.stdin.read()
        sys.stdout.write(strip_comments(source, _ext_of(args.filename)))
        return 0

    for path in args.files:
        with open(path, "r", encoding="utf-8") as f:
            source = f.read()
        stripped = strip_comments(source, _ext_of(path))
        if stripped != source:
            with open(path, "w", encoding="utf-8") as f:
                f.write(stripped)
    return 0


if __name__ == "__main__":
    sys.exit(main())
