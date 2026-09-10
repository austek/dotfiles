---
title: Add Context to Errors With context() and with_context()
impact: MEDIUM
impactDescription: Turns opaque low-level errors into a readable failure story
tags: [error-handling, anyhow, context, debugging]
---

# Add Context to Errors With context() and with_context() [MEDIUM]

## Description
Raw errors often only describe the immediate cause ("No such file or directory") without saying what operation was being attempted. Wrapping each fallible step with `.context()` or `.with_context()` builds an error chain that tells the full story: what you were trying to do, layered over why the underlying call failed.

## Bad Example
```rust
// Raw error - no context
fn load_user(id: u64) -> Result<User, Error> {
    let path = format!("users/{}.json", id);
    let content = std::fs::read_to_string(&path)?;
    Ok(serde_json::from_str(&content)?)
}
// Error message: "No such file or directory (os error 2)"
// Which file? What were we doing?
```

## Good Example
```rust
use anyhow::{Context, Result};

fn load_user(id: u64) -> Result<User> {
    let path = format!("users/{}.json", id);

    let content = std::fs::read_to_string(&path)
        .with_context(|| format!("failed to read user file: {}", path))?;

    let user: User = serde_json::from_str(&content)
        .with_context(|| format!("failed to parse user {} JSON", id))?;

    Ok(user)
}
// Error: "failed to parse user 42 JSON"
// Caused by: "expected ':' at line 5 column 12"
```

## Notes
- Use `.context("static message")` when the message needs no runtime data — it's slightly cheaper up front. Use `.with_context(|| format!(...))` when the message is built from runtime values or is otherwise costly, since the closure only runs on the error path.
- Chains compose across function boundaries: each layer (`fetch_order`, `load_user`, `process_payment`, `ship_order`) adds its own context, so the final error reads as a stack of "why", not just the innermost cause.
- Inspect a chain with `for cause in err.chain() { ... }`, or print `{:#}` for the collapsed one-line chain and `{:?}` for the full debug output with backtrace.

## References
- [err-anyhow-app](err-anyhow-app.md)
- [err-source-chain](err-source-chain.md)
- [err-question-mark](err-question-mark.md)
