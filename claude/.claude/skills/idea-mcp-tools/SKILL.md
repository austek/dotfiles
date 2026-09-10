---
name: idea-mcp-tools
description: >-
  Tool-selection rules for when the IntelliJ IDEA MCP server (`mcp__idea__*` tools) is
  connected. Consult this whenever exploring code (finding a symbol, its usages, or callers),
  checking whether a file compiles or lints, doing a multi-site rename or refactor, or
  debugging a runtime issue — the IDE's index and debugger are cheaper and faster than
  Bash/grep/Read for these. Always check this before reaching for grep, cat, a full
  Gradle/Maven/npm build, or a print-statement debugging loop when `mcp__idea__*` tools
  are present in the session's tool list, even if the user's request doesn't mention the IDE.
---

# IDE MCP Tool Selection

The IDE already parses and indexes the project. When `mcp__idea__*` tools are available,
re-deriving that information with grep/Read/full builds wastes tokens and wall-clock time.
Prefer the index-backed tool; fall back to filesystem tools only when the IDE tool is
unavailable, stale, or errors.

## Decision table

| Situation | Use | Instead of |
|---|---|---|
| Find a symbol's definition or usages | `search_symbol` / `get_symbol_info` | grep + Read each hit |
| "Who calls this" | `analyze_calls` | manual grep sweep for call sites |
| Text/pattern search across a large repo | `search_text` / `search_regex` / `list_directory_tree` | full filesystem grep |
| Module/dependency structure | `get_project_modules` / `get_project_dependencies` | parsing build files by hand |
| Does this file compile / lint | `get_file_problems` | full project build |
| Format/lint specific files | `lint_files` | full-repo lint task |
| Quick incremental compile signal | `build_project` | — see caveat below |
| Rename a symbol across all usages | `rename_refactoring` | manual find + edit per site |
| Multi-hunk structured edit | `apply_patch` | separate Read + Edit calls |
| Reformat one file | `reformat_file` | full-repo format task |
| Investigate runtime behavior of a bug | `xdebug_*` (breakpoints, stack, frame values, eval) | print/log statements + rerun loop |

## Caveats

- **`build_project` is not CI-equivalent.** It's a fast inner-loop signal only. Before
  claiming something builds or tests pass, run the project's real build/test command —
  check that repo's CLAUDE.md for the authoritative one (e.g. `./gradlew build` in dgc).
- **Avoid `generate_psi_tree` by default.** It's a full AST dump — expensive. Only reach
  for it when symbol-level info (`search_symbol`, `get_symbol_info`) genuinely isn't
  enough, e.g. an unusual syntax-level refactor.
- **`analyze_calls` times out at its default timeout in large monorepos.** Confirmed in
  dgc: both an external SDK method and a project-local method timed out at the default,
  then succeeded immediately with `timeout: 120000`. Retry once with an explicit large
  timeout before falling back to grep — it's a size/timeout problem, not a broken query.
- **Other stale or erroring results mean fall back, not retry.** These tools depend on the
  project being open and indexed in the IDE. A wrong-looking result or a repeated tool
  error (after the timeout bump above) is a signal the index is stale or the project
  isn't open — fall back to Bash/grep/Read rather than retrying the same call again.
- **No IDE connected → fall back silently.** If `mcp__idea__*` tools aren't in the
  current session's tool list, use normal tools without commentary.
