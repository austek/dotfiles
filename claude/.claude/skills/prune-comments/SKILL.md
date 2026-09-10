---
name: prune-comments
description: >-
  Judgment-based comment cleanup: keep only comments that encode a genuine,
  undiscoverable-from-the-code rationale (a platform/tool quirk, an ordering
  constraint, a cross-file fact, a safety/security consequence), cut anything
  that restates the code or defends a design choice nobody's questioning, and
  cap every surviving non-doc comment at 3 lines. Use when the user asks to
  "clean up comments", "be ruthless with comments", "audit comments", "trim
  comments", "prune comments", or asks whether a specific existing comment is
  "really needed" / "obvious from the code". This is a per-comment review,
  not a blind strip -- for "nuke/strip/delete all comments, no judgment", use
  nuke-comments instead. Takes an optional argument scoping the pass: a file
  or directory path, a PR number/URL, a branch name, or "full repo"/"repo".
  With no argument, scopes to uncommitted changes if there are any, and
  otherwise reports that there's nothing to prune rather than falling back
  to the whole repo.
argument-hint: "[path|branch|#PR|full repo] (optional; defaults to uncommitted changes)"
---

# Prune Comments

Reviews every existing comment against one bar and cuts anything that
doesn't clear it. This is not a style pass and not a rewrite — the code
itself never changes (except where the process below says the fix is to
simplify the code instead of commenting it), and no new comments get added
except the rare replacement noted below.

## Scope

Resolve `$ARGUMENTS` to a target in this order — stop at the first match:

1. **No argument** → run `git status --porcelain` (and `git diff --staged`
   if that's empty of unstaged-but-staged content). If there are
   uncommitted changes (staged or unstaged, tracked files), scope to those
   changed files — review comments the diff touches or sits next to, in
   the context of the full file, not just the hunk. If there are **no**
   uncommitted changes, say so and stop. Do not fall back to the whole
   repo — that must be requested explicitly (case 5).
2. **A filesystem path** that exists relative to the repo root (a file or
   directory) → scope to that path, same as before.
3. **A PR reference** (`#123`, `123`, `PR 123`, or a GitHub PR URL) →
   `gh pr diff <number> --name-only` for the file list. Review each file
   as it exists in that PR's branch (fetch/read via `gh pr diff` or
   `git show <remote>/<pr-branch>:<path>`), judging comments against their
   surrounding code, not the raw diff hunk. Only run `gh pr checkout` if
   you need a full local working tree for the compile/lint check in step
   4 of Process, and confirm with the user first since it switches
   branches.
4. **A branch name** that resolves via `git show-ref --verify` or appears
   in `git branch --list`/`git branch -r` → diff it against its merge base
   with the repo's default branch (`git merge-base <branch> origin/HEAD`)
   and scope to the files that diff touches, same review discipline as
   the PR case.
5. **An explicit whole-repo request** ("full repo", "whole repo", "repo",
   "everything", "all") → the entire repo is in scope.
6. Anything that matches none of the above (typo'd path, unknown branch,
   PR number that doesn't exist) → say so and ask, rather than guessing
   or silently widening scope.

Regardless of scope, skip: `.git`, build/output dirs (`target`, `dist`,
  `build`, `node_modules`, `.venv`, `__pycache__`), and anything vendored or
  not authored by this repo (git submodules, `deps/`, `third_party/`,
  vendored crates/packages, generated code). If unsure whether a directory
  is vendored, check for its own `LICENSE`/`.git`/lockfile before touching it.
- On a whole-repo pass, work one crate/package/module directory at a time
  rather than trying to hold the whole tree in context at once. If the repo
  is large, consider forking one subagent per top-level module so each pass
  stays focused — but do the judgment calls yourself in each fork; don't
  delegate the "is this obvious from the code" question to a script.

## The bar

For every comment (`//`, `#`, `--`, whatever the language uses — **not**
doc comments, see below), ask: **would a careful reader lose real
information if this comment vanished?** Delete unless the answer is yes.

**Delete — restates the code.** If the comment just narrates what the next
line does, the identifier names already do that job.
```
# Only a definite 404 means "not published yet"
case "$status" in
  200) ... ;;
  404) ... ;;
  *) exit 1 ;;   # <- the code already says "anything else fails"
esac
```
The `case` statement's branches are the documentation. Delete.

**Delete — design defense.** A comment justifying *why* a choice was made,
when nobody reading the code needs to be talked out of a different choice,
is a defense, not information. "So one decision unblocks all four together"
next to a `needs: approve` a reader can already see on four jobs is a
defense. Delete it; the graph speaks for itself.

**Delete — redundant with a sibling.** If an input's own `description:`
field, a docstring, or a type already says the same thing the comment
above it says, the comment is a second copy that will drift from the first.
Delete the comment, keep the single source of truth.

**Delete — commented-out code.** Git history holds it. No exceptions.

**Keep, trimmed to ≤3 lines — genuine undiscoverable rationale.** Keep
only when the comment is one of:
- a platform/tool quirk (e.g. "GH Actions `run:` steps execute as `bash -e
  {0}` regardless of this script's own `set` flags" — a fact about the
  runtime, not the code)
- an ordering/timing constraint that isn't visible from reading top-to-bottom
- a cross-file fact (behavior that depends on another file the reader isn't
  looking at right now)
- a safety/security consequence that isn't obvious from the change itself
  (a silent-failure mode, a bypassed gate, a downstream break)
- a historical gotcha ("a prefix collision has already bitten this repo
  once") that would otherwise tempt a future edit into repeating it

Trim ruthlessly even when keeping: cut every clause that's justification
rather than fact. Three lines is a hard cap, not a target — if it doesn't
fit in three, cut content, don't wrap wider.

**Simplify instead of commenting.** If a block of code is genuinely too
complex to be understood by reading it — and the honest comment needed to
explain it would run long — that's a signal the code needs restructuring,
not a long comment. Flag this to the user rather than writing the long
comment: name the file/lines and what's tangled, and let them decide
whether to simplify now or accept the comment as a stopgap.

## What never gets touched

- License/copyright headers.
- `SAFETY:` / `# Safety` comments required above `unsafe` blocks or on
  `unsafe fn` (this project's CLAUDE.md mandates these; removing one is a
  correctness/policy regression, not a cleanup).
- Doc comments (`///`, `/** */`, docstrings, YARD/JSDoc/rustdoc-style
  blocks) — these follow a different rule entirely (state the contract,
  no signature narration) and are out of scope for this skill. Don't prune
  a docstring just because it's long; that's a separate, judgment-heavier
  review.
- `CLAUDENOTE:`-prefixed scratch comments, if present — those are meant to
  be stripped at final commit by whoever wrote them, not by this pass.

## Process

1. Resolve scope from `$ARGUMENTS` (see above).
2. For each file in scope, find every comment. Read enough surrounding code
   to judge each one against the bar — don't judge a comment from a grep
   snippet alone.
3. Edit in place: delete what fails the bar, trim what survives to ≤3
   lines. Don't touch code logic. Don't add new comments except when a
   trim genuinely needs to relocate a still-load-bearing fact to a
   different, more precise attachment point (this happened during the
   session this skill was built from: a 3-line justification covering two
   unrelated facts was split into two 1-line comments, each attached to
   the specific line it actually explains).
4. After editing a file, verify it still parses/compiles/lints cheaply
   (language-appropriate: `python3 -c "import yaml; yaml.safe_load(open(f))"`
   for YAML, `cargo check`/`rustc --edition ... --crate-type lib -o /dev/null`
   for Rust snippets, etc.) — a syntax error from a bad edit is worse than
   any comment.
5. Re-scan each touched file for any remaining comment block over 3 lines
   and any comment referencing something you just deleted elsewhere (a
   "see the trigger comment above" pointing at a block you cut) — fix or
   remove those too.

## Reporting

Summarize per file: lines of comment removed vs. kept, and call out (a)
any comment kept that's borderline (so the user can veto it) and (b) any
"code is too complex, simplify instead" flags from step above. Don't dump
the full diff in chat unless asked — a stat summary plus the flagged
borderline cases is the report.
