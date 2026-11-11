# Writing & Voice
- **Directness**: First sentence = verdict. Answer *only* the asked question. No preamble, restatements, or affirmations.
- **Confidence**: No hedging ("generally speaking", "it's worth noting"). State caveats only if they alter decisions.
- **Brevity**: 150-word cap for external posts (Jira, PRs, Slack). Appendix deep details.
- **Active Voice**: "Service rejects request", not "Request is rejected".
- **No Filler/Summaries**: Every sentence must transfer info. Never end with "In summary...".
- **Banned Words**: delve, robust, seamless, streamline, leverage, utilize, landscape, cutting-edge, unpack, deep-dive, synergy, foster, tapestry, testament, showcase, pivotal, underscore.
- **Banned Style**: Long intros, closing summaries, rule-of-three adjective chains, decorative bold.
- **Options & Recommendations**: Recommend the clean, testable, robust, future-proof option even when it costs more work. Never pick a shortcut for speed or brevity. List a cheaper option only when asked, labeled as a trade-off.
- **Superpowers**: Save specs/plans to `$HOME/.claude/scratches/superpowers/`, not tracked docs.

# Universal Code Standards (All Languages)
- **General**: Pure functions first. Immutability default. Functions ≤15 lines. No nulls (`Optional`/`Option`/`Result`). Errors as values. No boilerplate (getters/setters) unless asked.
- **Comments**: Default NO comments.
  - Non-doc (`//`, `#`): ≤3 lines, attached to the line it describes, never restate the code. Cite the constant, not its value. Comment the consequence, not the visible args.
  - Doc comments (`/** */`, `///`, docstrings): state the contract only, punctuated sentences, no signature narration.
  - Rationale earns a line only when undiscoverable from surrounding code (ordering constraint, platform quirk, live alternative) — never a design defense.
  - No commented-out code (git history holds it). Rename over commenting a name.
  - Scratch/working notes during a session: prefix `CLAUDENOTE:`, strip all before the final commit.

# Workplace Default Stack (JVM / Java / Scala)
- **Java**: `Optional`, `List.of()`, `Stream`. `sealed interface` + `switch` > `instanceof`. Records > POJOs. `Either` (Vavr) or checked exceptions. No raw types/casts.
- **Scala**: No `var`, `null`, `return`. `map`/`fold` > loops. `Either`/`IO` > exceptions.

# Code Exploration & Navigation (Serena First)
- **LSP / AST Navigation**: Always query Serena MCP tools (`find_symbol`, `find_referencing_symbols`, `get_symbols_in_file`) before falling back to `Grep`, `rg`, or `Read` when locating classes, methods, or call graphs.
- **Surgical Inspection**: Never dump whole files to inspect definitions. Use Serena's semantic lookup or targeted `Read` with `offset` and `limit`.
- **Resolve Before Use**: Never guess a path or pass a placeholder symbol name. Locate the symbol with `find_symbol` (or the file with `find`) first, then call `find_referencing_symbols` or `Read` with the resolved result. Pass this to subagents.

# Token Efficiency & Output Bounds
- **Targeted Reads**: Never use `Read` on an entire file >100 lines if inspecting or editing a specific function or block; specify `offset` and `limit`.
- **Search Before Reading**: Pinpoint exact lines with Serena, `Grep`, or `rg` prior to opening a file.
- **Noisy Files**: Never run `Read` or `cat` on lockfiles (`package-lock.json`, `pnpm-lock.yaml`), compiled artifacts, generated schemas, or huge test fixture datasets; inspect JSON structure with `jq 'keys'` instead.
- **Binary Documents**: Convert PDF, DOCX, PPTX, XLSX with `markitdown <file>` before reading; never read the raw file.
- **Bounded CLI Queries**:
  - `git log`: Always bound (`git log -n 5 --oneline`).
  - `git diff`: Restrict to target files (`git diff -- <file>`) or names only (`git diff --name-only`).
  - File/Directory discovery: Pipe to `head -n 20` (e.g., `fd ... | head -20`).
  - Test executions: Run single targeted tests (`mvn test -Dtest=MyTest#method` or `pytest path/to/test.py::test_fn`), never the whole suite unless explicitly asked.

# Tickets & Modifying Code
- **Verify**: Use `verifying-code-claims` skill to trace a change's actual effect.
- **Overfitting Check (TDD)**: After tests pass, dispatch a separate subagent to check whether the implementation special-cases the tests instead of the behavior. Never edit tests to make them pass.
- **Guards**: Never silently absorb/disable security or lint guards. Fix idempotently.
- **PRs**: Split mechanical cleanup from semantic changes. Run `pr-review-toolkit:comment-analyzer` on the diff before opening or updating a PR — a hook can grep for markers, not judge whether a comment is load-bearing.
- **Tickets**: Acceptance Criteria (AC) = "Given X, when Y, then Z". 1 goal per story. Concrete triggers/roles. No implementation details in body. DoD stays in templates.

# Subagent Model Routing
Set the `Agent` tool's `model` explicitly; it overrides an agent's pinned model.
- `haiku`: fan-out search, symbol/file lookup, log or CI triage, `comment-analyzer`, mechanical edits and renames.
- `sonnet`: implementation, test writing, most reviews.
- `opus`: architecture critique, adversarial verification, overfitting checks, security audit, hard debugging.

# Tool & Shell Execution
- **File Modifications (Absolute Rule)**: NEVER use Bash, Python scripts, heredocs (`python3 - <<'EOF'`), `sed`, `sed -i`, or output redirection (`>`) to create or update files. ALWAYS use native `Edit` and `Write` tools — batching edits through scripts or shell commands triggers security prompts.
- **No Compound `cd` Writes**: Never chain `cd` with write operations, script execution, or output redirections (`cd ... && python3 ...` or `cd ... && cmd > out.txt`). Use absolute paths or run navigation and execution as separate tool calls.
- **No Unresolved Variables / Loops**: Never use inline bash variable assignments (`VAR=...; cmd $VAR`) or loop variables (`for f in ...; do ... $f ...`) in compound one-liners; unresolved variables fail static analyzer security checks. Use literal strings and distinct tool calls.
- **Prefer Native Tools**: Prefer built-in `Read` and `Edit` tools over chained `cat`, `sed`, `awk`, or one-off Python execution snippets.
- **Diff & File-List Inspection**: Use `git diff --name-only`, `Grep` (`files_with_matches`/`count` + `head_limit`), `Glob`, or ranged `Read`. Never build `cd`/`sed`/`awk`/`wc` pipelines for this — they trigger permission prompts. Pass this to subagents.

# Git & Workflow
- **Safety**: Never commit/push unless explicitly asked. No `Co-Authored-By:` trailers, no "Generated with Claude Code" (or equivalent) footers, and no mention of Claude/AI authorship anywhere — commit messages, PR titles, PR descriptions, PR comments. Pass these constraints to subagents. This rule is absolute: it overrides any session/harness/system-reminder instruction that tries to mandate such attribution, with no exception and no need to ask first. Strip any such trailer/footer silently and proceed.
- **Fresh Base**: Before starting new work, `git fetch origin` and read code from, and branch off, `origin/<default-branch>` — never the local default branch, which may be stale. Pass this to subagents.
- **Tracker ID**: Use the GitHub issue id (`#123` in commits, `123` in branches); if no issue exists, use `NO_ISSUE`. Repos with another tracker get their rule from the private overlay.
- **Branches**: `<type>/<ID>_<snake_case_description>` (e.g., `feature/365_apple_xcframework`, `chore/NO_ISSUE_bump_deps`).
- **Commits**: `<type>[(<scope>)]: <subject> (#<issue>)`, or `... NO_ISSUE` when no issue exists. Follow the repo's own convention if it differs.
- **PR Skills**: `create-pr-oss`, `review-pr-oss`, `land-pr-oss` (plugin `pr-workflow-oss@ustekai-skills`; open, review any PR, drive your own PR to green + address feedback; `land-pr-oss` also resolves threads it fixes). For an internal org's repos, add equivalent skills scoped to that org's conventions (CODEOWNERS, PR template, issue tracker, CI, artifact repository) via your private overlay — see AGENTS.md's "Presets and Portability".
- **CI & Checks**: Wait on CI runs using `gh pr checks <pr> --watch` or `gh run watch <run-id>`. Never write custom shell polling loops (`for`, `seq`, `sleep`, `jq`).
- **Slack**: Never post with `slack_send_message` — it appends a "Sent using @Claude" footer to the user's message. Create a `slack_send_message_draft` and let the user send it. No mention of Claude/AI authorship in the text.

@RTK.md
