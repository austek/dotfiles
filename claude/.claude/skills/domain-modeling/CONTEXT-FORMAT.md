# CONTEXT.md Format

## Template
```md
# {Context Name}
{1-2 sentences: what this context is and why it exists.}

## Language

**{Term}**:
{1-2 sentences: what it IS, not what it does.}
_Avoid_: {Synonyms}
```

## Rules
- **Opinionated**: Pick canonical term, list others under `_Avoid_`.
- **Domain Only**: Strictly exclude general programming concepts (timeouts, errors).
- **Grouping**: Group under subheadings for natural clusters; otherwise use flat list.

## Single vs. Multi-Context
- **Single**: One `CONTEXT.md` at repo root.
- **Multi**: Root `CONTEXT-MAP.md` mapping contexts to paths (e.g., `[Ordering](./src/ordering/CONTEXT.md)`).
- **Routing**: If `CONTEXT-MAP.md` exists, read it to find the target context. Else use root. Create root lazily if neither exists.
