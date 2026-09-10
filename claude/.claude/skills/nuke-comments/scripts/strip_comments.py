#!/usr/bin/env python3
"""strip-comments: Syntax-aware comment remover for multiple programming languages.

Supports:
- C-style (// and /* */): Rust, Java, Scala, C, C++, C#, Go, JS, TS, Proto, Kotlin, Swift, PHP, etc.
- Hash-style (#): Python, Bash/Shell, YAML, Ruby, Perl, R, Dockerfile, etc.
- SQL / Lua (--): SQL, Lua, Haskell
"""

import os
import sys
from pathlib import Path

SYNTAX_CONFIG = {
    "rust": {
        "exts": {".rs"},
        "line": ["//"],
        "block": [("/*", "*/")],
        "nest_block": True,
        "raw_string": "rust",
    },
    "c_family": {
        "exts": {
            ".c", ".h", ".cpp", ".hpp", ".cc", ".cxx", ".java", ".scala", ".kt", ".kts",
            ".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx", ".proto", ".go", ".cs", ".swift",
            ".php", ".dart", ".zig", ".jsonc",
        },
        "line": ["//"],
        "block": [("/*", "*/")],
        "nest_block": False,
        "raw_string": None,
    },
    "hash_family": {
        "exts": {
            ".py", ".pyw", ".sh", ".bash", ".zsh", ".rb", ".yaml", ".yml", ".toml", ".r",
            ".pl", ".pm", "dockerfile", ".dockerfile",
        },
        "line": ["#"],
        "block": [],
        "nest_block": False,
        "raw_string": "python",
    },
    "dash_family": {
        "exts": {".sql", ".lua", ".hs"},
        "line": ["--"],
        "block": [("/*", "*/")],
        "nest_block": False,
        "raw_string": None,
    },
}

IGNORED_DIRS = {
    ".git", "target", "node_modules", ".build", "build", "dist", ".idea", ".vscode",
    ".venv", "venv", "__pycache__",
}


def get_syntax(path: Path):
    name = path.name.lower()
    ext = path.suffix.lower()
    for config in SYNTAX_CONFIG.values():
        if ext in config["exts"] or name in config["exts"]:
            return config
    return None


def strip_source(source: str, cfg: dict) -> str:
    shebang = ""
    if "#" in cfg["line"] and source.startswith("#!"):
        newline_idx = source.find("\n")
        if newline_idx == -1:
            return source
        shebang = source[: newline_idx + 1]
        source = source[newline_idx + 1 :]

    out = []
    i = 0
    n = len(source)

    line_delims = cfg["line"]
    block_pairs = cfg["block"]
    nest_block = cfg["nest_block"]
    raw_mode = cfg["raw_string"]

    STATE_CODE = 0
    STATE_STR_SINGLE = 1
    STATE_STR_DOUBLE = 2
    STATE_STR_BACKTICK = 3
    STATE_STR_TRIPLE_SINGLE = 4
    STATE_STR_TRIPLE_DOUBLE = 5
    STATE_STR_RAW_RUST = 6
    STATE_LINE_COMMENT = 7
    STATE_BLOCK_COMMENT = 8

    state = STATE_CODE
    comment_depth = 0
    raw_rust_hashes = 0
    active_block_close = ""

    while i < n:
        c = source[i]
        c_next = source[i + 1] if i + 1 < n else ""
        c_next2 = source[i + 2] if i + 2 < n else ""

        if state == STATE_CODE:
            if raw_mode == "rust" and c == "r" and (c_next == '"' or c_next == "#"):
                hashes = 0
                idx = i + 1
                while idx < n and source[idx] == "#":
                    hashes += 1
                    idx += 1
                if idx < n and source[idx] == '"':
                    state = STATE_STR_RAW_RUST
                    raw_rust_hashes = hashes
                    out.append(source[i : idx + 1])
                    i = idx + 1
                    continue

            if raw_mode == "python":
                if c == '"' and c_next == '"' and c_next2 == '"':
                    state = STATE_STR_TRIPLE_DOUBLE
                    out.append('"""')
                    i += 3
                    continue
                if c == "'" and c_next == "'" and c_next2 == "'":
                    state = STATE_STR_TRIPLE_SINGLE
                    out.append("'''")
                    i += 3
                    continue

            is_line_comment = False
            for l_delim in line_delims:
                if source.startswith(l_delim, i):
                    state = STATE_LINE_COMMENT
                    i += len(l_delim)
                    is_line_comment = True
                    break
            if is_line_comment:
                continue

            is_block_comment = False
            for b_open, b_close in block_pairs:
                if source.startswith(b_open, i):
                    state = STATE_BLOCK_COMMENT
                    active_block_close = b_close
                    comment_depth = 1
                    i += len(b_open)
                    is_block_comment = True
                    break
            if is_block_comment:
                continue

            if c == '"':
                state = STATE_STR_DOUBLE
                out.append(c)
                i += 1
                continue
            if c == "'":
                is_lifetime = (
                    raw_mode == "rust"
                    and c_next != "\\"
                    and c_next2 != "'"
                )
                if is_lifetime:
                    # Rust lifetime (`'a`, `'static`, ...) looks like a char-literal
                    # start but is never closed — treating it as a string would make
                    # STATE_STR_SINGLE consume the rest of the file waiting to close.
                    out.append(c)
                    i += 1
                    continue
                state = STATE_STR_SINGLE
                out.append(c)
                i += 1
                continue
            if c == "`":
                state = STATE_STR_BACKTICK
                out.append(c)
                i += 1
                continue

            out.append(c)
            i += 1

        elif state == STATE_LINE_COMMENT:
            if c == "\n":
                out.append("\n")
                state = STATE_CODE
            i += 1

        elif state == STATE_BLOCK_COMMENT:
            if nest_block and source.startswith("/*", i):
                comment_depth += 1
                i += 2
            elif source.startswith(active_block_close, i):
                comment_depth -= 1
                i += len(active_block_close)
                if comment_depth <= 0:
                    state = STATE_CODE
            else:
                if c == "\n":
                    out.append("\n")
                i += 1

        elif state == STATE_STR_DOUBLE:
            out.append(c)
            if c == "\\" and i + 1 < n:
                out.append(c_next)
                i += 2
                continue
            if c == '"':
                state = STATE_CODE
            i += 1

        elif state == STATE_STR_SINGLE:
            out.append(c)
            if c == "\\" and i + 1 < n:
                out.append(c_next)
                i += 2
                continue
            if c == "'":
                state = STATE_CODE
            i += 1

        elif state == STATE_STR_BACKTICK:
            out.append(c)
            if c == "\\" and i + 1 < n:
                out.append(c_next)
                i += 2
                continue
            if c == "`":
                state = STATE_CODE
            i += 1

        elif state == STATE_STR_TRIPLE_DOUBLE:
            out.append(c)
            if c == "\\" and i + 1 < n:
                out.append(c_next)
                i += 2
                continue
            if c == '"' and c_next == '"' and c_next2 == '"':
                out.append('""')
                i += 3
                state = STATE_CODE
                continue
            i += 1

        elif state == STATE_STR_TRIPLE_SINGLE:
            out.append(c)
            if c == "\\" and i + 1 < n:
                out.append(c_next)
                i += 2
                continue
            if c == "'" and c_next == "'" and c_next2 == "'":
                out.append("''")
                i += 3
                state = STATE_CODE
                continue
            i += 1

        elif state == STATE_STR_RAW_RUST:
            out.append(c)
            if c == '"' and source[i + 1 : i + 1 + raw_rust_hashes] == "#" * raw_rust_hashes:
                out.append("#" * raw_rust_hashes)
                i += 1 + raw_rust_hashes
                state = STATE_CODE
                continue
            i += 1

    return shebang + remove_comment_blank_lines(source, "".join(out))


def remove_comment_blank_lines(original: str, cleaned: str) -> str:
    """Drop lines that became blank solely because a comment was removed,
    while preserving lines that were already blank in the original."""
    orig_lines = original.splitlines(keepends=True)
    clean_lines = cleaned.splitlines(keepends=True)
    result = []
    for orig_line, clean_line in zip(orig_lines, clean_lines):
        if clean_line.strip() == "" and orig_line.strip() != "":
            continue
        result.append(clean_line)
    return "".join(result)


def find_files(target: Path):
    if target.is_file():
        if get_syntax(target):
            yield target
        return
    for root, dirs, files in os.walk(target):
        dirs[:] = [d for d in dirs if d not in IGNORED_DIRS and not d.startswith(".")]
        for file in files:
            p = Path(root) / file
            if get_syntax(p):
                yield p


def main():
    args = sys.argv[1:]
    if not args or "-h" in args or "--help" in args:
        print(
            "Usage: strip_comments.py [-i|--in-place] <path ...>\n\n"
            "Options:\n"
            "  -i, --in-place   Modify files in-place (default: write to stdout)\n"
            "  -h, --help       Show this help"
        )
        sys.exit(0)

    in_place = "-i" in args or "--in-place" in args
    targets = [a for a in args if a not in ("-i", "--in-place")]

    if not targets:
        print("Error: No paths provided.", file=sys.stderr)
        sys.exit(1)

    for target_str in targets:
        target = Path(target_str)
        if not target.exists():
            print(f"Warning: path not found: {target}", file=sys.stderr)
            continue
        for path in find_files(target):
            cfg = get_syntax(path)
            if not cfg:
                continue
            try:
                content = path.read_text(encoding="utf-8")
                cleaned = strip_source(content, cfg)
                if in_place:
                    path.write_text(cleaned, encoding="utf-8")
                    print(f"Stripped: {path}")
                else:
                    sys.stdout.write(cleaned)
            except Exception as e:  # noqa: BLE001 -- one bad file must not abort the batch
                print(f"Error reading {path}: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
