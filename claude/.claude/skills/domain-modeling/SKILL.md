---
name: domain-modeling
description: Build and sharpen project's domain model (glossary/ADRs). Use when modifying CONTEXT.md or ADRs.
---

# Domain Modeling

Actively build/sharpen the domain model (do not use this skill just to *read* terminology).

## File Structure
- **Single Context**: `/CONTEXT.md`, `/docs/adr/0001-slug.md`.
- **Multi-Context**: `/CONTEXT-MAP.md`, `/src/<context>/CONTEXT.md`, `/src/<context>/docs/adr/`.
- Create files lazily (only when resolving first term/ADR).

## Session Rules
- **Challenge Glossary**: Call out user conflicts with existing `CONTEXT.md` terms immediately.
- **Sharpen Language**: Reject fuzzy/overloaded terms (e.g., "account"); propose precise canonical terms.
- **Concrete Scenarios**: Stress-test relationships with edge cases to force boundary precision.
- **Cross-Reference Code**: Flag contradictions between user statements and actual code behavior.
- **Update Inline**: Update `CONTEXT.md` immediately upon term resolution. Zero implementation details allowed (strict glossary). Format via `CONTEXT-FORMAT.md`.
- **Offer ADRs Sparingly**: Apply the 3-rule test (Hard to reverse + Surprising + Real trade-off). Format via `ADR-FORMAT.md`.
