---
name: improve-codebase-architecture
description: Scan codebase for deepening opportunities, present visual HTML report, and grill user on selection.
disable-model-invocation: true
---

# Improve Codebase Architecture

Propose **deepening opportunities** to turn shallow modules into deep ones.
- **Vocab (`/codebase-design`)**: module, interface, depth, seam, adapter, leverage, locality. NO substitutions (e.g., API, component, service).
- **Domain (`CONTEXT.md`)**: Use exact domain names.
- **ADRs**: Respect `docs/adr/`.

## 1. Explore
- **Scope**: Target user-specified areas OR git commit hot spots.
- **Scan**: Find shallow modules, leaky seams, scattered complexity, and untested parts.
- **Test**: Apply "deletion test" (does deleting the module concentrate or just move complexity?).

## 2. HTML Report
- **Output**: Write self-contained HTML to `<tmpdir>/architecture-review-<timestamp>.html` (`$TMPDIR`, `/tmp`, or `%TEMP%`).
- **Open**: Auto-open via `xdg-open <path>`, `open <path>`, or `start <path>`. Print absolute path.
- **Content**: See `HTML-REPORT.md` for Tailwind/Mermaid scaffolding and diagram patterns.
- **Cards**: Include Files, Problem, Solution, Benefits, Before/After diagram, Recommendation badge.
- **ADRs**: Call out conflicts only if friction justifies reopening.
- **Next**: Do NOT propose interfaces. Ask: "Which of these would you like to explore?"

## 3. Grilling Loop
User picks candidate -> run `/grilling` skill.
- **Domain Modeling**: Run `/domain-modeling` inline to add/sharpen terms in `CONTEXT.md`.
- **ADRs**: If user rejects candidate for load-bearing reasons, offer to record an ADR.
- **Interfaces**: To explore alternative interfaces, run `/codebase-design` (design-it-twice pattern).
