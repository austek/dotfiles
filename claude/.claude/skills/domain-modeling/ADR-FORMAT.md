# ADR Format

**Location**: `docs/adr/0001-slug.md` (sequential numbering). Create `docs/adr/` lazily.
**Numbering**: Scan `docs/adr/`, increment highest existing by 1.

## Template
```md
# {Short title of the decision}
{1-3 sentences: context, decision, and rationale.}
```

**Optional Sections** (Status, Considered Options, Consequences) only if adding genuine value.

## When to Offer an ADR
All three MUST be true to warrant an ADR:
- **Hard to reverse**: Meaningful cost to change later.
- **Surprising**: Future readers will wonder "why?"
- **Real trade-off**: Genuine alternatives existed.

**Qualifies**: Architecture, integrations, lock-in tech, boundaries, deliberate deviations, invisible constraints, non-obvious rejections.
