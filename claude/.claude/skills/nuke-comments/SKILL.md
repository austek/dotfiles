---
name: nuke-comments
description: >-
  Mechanically strip every comment from source files in one pass, with zero
  per-comment review or judgment — a fast syntax-driven deletion, not a
  quality/cleanup pass. Use whenever the user says to "nuke", "strip", "wipe",
  "delete all", or "remove all" comments, wants comments gone with "no
  checking" or "don't review them", or explicitly rejects a judgment-based
  comment cleanup in favor of blind removal. Do NOT use this for requests like
  "clean up bad comments", "remove redundant/tutorial comments", or "improve
  comment quality" — those need per-comment judgment (SAFETY docs, license
  headers, and public API docs must survive that kind of pass); this skill
  removes literally all of them, no exceptions, and is for when the user
  explicitly wants that. Takes an optional argument scoping the pass: a file
  or directory path, a PR number/URL, a branch name, or "full repo"/"repo".
  With no argument, scopes to uncommitted changes if there are any, and
  otherwise reports that there's nothing to strip rather than defaulting to
  the whole repo.
argument-hint: "[path|branch|#PR|full repo] (optional; defaults to uncommitted changes)"
---

# Nuke Comments

Deletes every comment in the target file(s) or directory, unconditionally.
There's no distinction here between a tutorial comment and a required
`SAFETY:` note, a license header, or a public API doc comment — they're all
comments, so they all go. This only exists because the user has explicitly
chosen blind, no-review removal over a judgment-based cleanup — don't use it
when the actual ask is "clean up bad comments" or "improve comment quality."

**Before running this on a real codebase, say once, plainly, what it will
also remove: license/copyright headers, `SAFETY:`/`# Safety` doc comments on
`unsafe` code, and public API docs (rustdoc/Javadoc/godoc/docstrings).** State
it and proceed — the user has already decided this tradeoff is what they
want; don't turn it into a confirmation gate or ask again.

## How it works

A bundled Python state machine (`scripts/strip_comments.py`) tracks whether
the parser is inside a string, a raw/triple-quoted string, a line comment, or
a block comment (with nesting for Rust's `/* /* */ */`), so it only deletes
actual comments and never touches `//` or `#` sitting inside a string literal
or a URL in a string. It needs nothing beyond Python 3's standard library.

Supported by extension:
- **Rust** (`.rs`) — `//`, `/* */` (nested), and `r"..."` / `r#"..."#` raw strings
- **C-family** (`.c .h .cpp .hpp .cc .cxx .java .scala .kt .kts .js .jsx .mjs .cjs .ts .tsx .proto .go .cs .swift .php .dart .zig .jsonc`) — `//`, `/* */`
- **Hash-family** (`.py .pyw .sh .bash .zsh .rb .yaml .yml .toml .r .pl .pm`, `Dockerfile`) — `#`
- **Dash-family** (`.sql .lua .hs`) — `--`, plus `/* */` for SQL

Anything else (e.g. plain YAML edge cases, exotic languages) is skipped
silently — the tool never guesses at a syntax it wasn't given.

## Known limitation: cgo preambles

In Go files that `import "C"`, the `/* ... */` block immediately above that
import isn't documentation — cgo compiles its contents as literal C, so
`#include`s, `#cgo` directives, and any C declarations placed in there are
real code wearing a Go comment as a syntax requirement. This tool can't
distinguish that from an ordinary comment and will delete C code along with
it, breaking the build (symptom: `could not determine kind of name for
C.foo`). If a repo has `.go` files using cgo, check `go build ./...`
afterward and be ready to manually restore anything load-bearing that lived
inside a cgo preamble.

## Scope

Resolve `$ARGUMENTS` to a target in this order — stop at the first match:

1. **No argument** → run `git status --porcelain` (staged and unstaged,
   tracked files). If there are uncommitted changes, target those changed
   files' paths directly. If there are **none**, say so and stop — don't
   fall back to stripping the whole repo, that must be requested explicitly
   (case 5).
2. **A filesystem path** that exists relative to the repo root (a file or
   directory) → target it directly, same as before.
3. **A PR reference** (`#123`, `123`, `PR 123`, or a GitHub PR URL) →
   `gh pr diff <number> --name-only` for the file list; target those paths
   as they exist in the current working tree (`gh pr checkout <number>`
   first only if the files aren't present locally, and confirm with the
   user first since it switches branches).
4. **A branch name** that resolves via `git show-ref --verify` or appears
   in `git branch --list`/`git branch -r` → diff it against its merge base
   with the repo's default branch (`git merge-base <branch> origin/HEAD`)
   and target the files that diff touches.
5. **An explicit whole-repo request** ("full repo", "whole repo", "repo",
   "everything", "all") → target the repo root, same as passing it as a
   directory.
6. Anything that matches none of the above (typo'd path, unknown branch,
   PR number that doesn't exist) → say so and ask, rather than guessing or
   silently widening scope.

## Running it

```bash
python3 ~/.claude/skills/nuke-comments/scripts/strip_comments.py -i <path> [<path> ...]
```

- `<path>` can be a single file, a directory (recursed automatically), or
  several of either — pass one argument per file/directory the scope
  resolution above landed on (e.g. every changed file for the no-argument
  or PR/branch cases, or the repo root for the whole-repo case).
- `-i` / `--in-place` writes the stripped result back to each file. Without
  it, the tool writes to stdout instead — useful for a quick look, but for
  the "just remove them" workflow this skill exists for, use `-i`.
- `.git`, `target`, `node_modules`, `.build`, `build`, `dist`, `.idea`,
  `.vscode`, `.venv`, `venv`, `__pycache__`, and any other dot-directory are
  skipped automatically.

## Reporting back

The script prints one `Stripped: <path>` line per file it actually modified,
plus `Warning:`/`Error:` lines for anything it couldn't read. After running,
just relay that file list back to the user — that's the whole report. Don't
open the diff, don't walk through what got removed, don't add anything back.
That's the point of this skill over the judgment-based cleanup workflow.
