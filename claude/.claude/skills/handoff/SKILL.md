---
name: handoff
description: >-
  Compact the current conversation into a handoff document for a fresh agent to pick up.
argument-hint: "What will the next session be used for?"
disable-model-invocation: true
---

# Agent Handoff Document Generation

Summarize the current conversation to allow a fresh agent to seamlessly continue the work.

## Requirements
- **Destination**: Save the document to `$HOME/.claude/scratches/handoff/`. If a dev ticket, issue, or PR number is available for the work, save under a subfolder named for it (e.g. `.../handoff/DEV-1234/`); otherwise save directly in the `handoff/` directory. Do NOT save in the current workspace.
- **Focus**: Use `$ARGUMENTS` (if provided) as the description of the next session's focus and tailor the document accordingly.
- **Content**: Must include a "Suggested skills" section outlining which skills the next agent should invoke.
- **References**: Do NOT duplicate content already captured in other artifacts (specs, plans, ADRs, issues, commits, diffs). Reference them by path or URL instead.
- **Security**: Strictly redact any sensitive information (API keys, passwords, PII).
