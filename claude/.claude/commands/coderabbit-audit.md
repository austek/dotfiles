---
description: Run a full-repo CodeRabbit audit (not just the diff) and summarize the findings
allowed-tools: Bash, Read
---

Run a full-codebase CodeRabbit review via the `coderabbitFullAudit` script (installed as part of the `local` dotfiles package) and report the results.

### Step 1: Preconditions
1. Confirm the current directory is a git repository and `.coderabbit.yaml` is tracked on the current branch. If either is missing, stop and tell the user what's missing — the script itself also checks this and will exit with a clear error.
2. Confirm the `coderabbit` CLI is on `PATH` (`command -v coderabbit`) and authenticated (`coderabbit auth status` or equivalent). If not installed, tell the user to run the `personal` profile's `setup.sh`, which installs it; if not authenticated, tell them to run `coderabbit auth login`.

### Step 2: Run the audit
Run `coderabbitFullAudit` via Bash from the repo root. This script:
- Creates a scratch worktree, diffs the current tree against an empty baseline (respecting `.coderabbit.yaml`'s negated `path_filters`), and runs `cr review --base audit-base --agent`.
- Cleans up the scratch worktree on exit.
- Exports the raw review to `~/.claude/scratches/handoff/coderabbit_full_audit.md`.

This can take several minutes on a large repo — do not cancel early.

### Step 3: Summarize
Read `~/.claude/scratches/handoff/coderabbit_full_audit.md` and present the findings grouped by severity (blocker/critical first), each with the file:line it applies to and a one-line fix suggestion. Do not restate findings CodeRabbit marked as nitpicks unless the user asks for them.
