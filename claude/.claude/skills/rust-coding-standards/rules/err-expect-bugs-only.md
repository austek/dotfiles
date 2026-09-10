---
title: Reserve expect() for Invariants, Not User or External Errors
impact: MEDIUM
impactDescription: Panic messages point straight at the actual bug
tags: [error-handling, expect, panics, invariants]
---

# Reserve expect() for Invariants, Not User or External Errors [MEDIUM]

## Description
`expect()` is better than `unwrap()` because it carries a message, but it still panics. Reserve it for situations where failure would mean a bug in your own code — a violated invariant — never for user input, file I/O, or network calls, which can legitimately fail for reasons outside your control. The message should explain *why* the invariant is expected to hold, so whoever hits the panic can go straight to the actual bug instead of guessing.

## Bad Example
```rust
// User input can legitimately fail - don't expect
fn parse_user_input(input: &str) -> Config {
    serde_json::from_str(input)
        .expect("Invalid JSON") // User error, not a bug!
}

// File might not exist - don't expect
fn load_config() -> Config {
    let content = fs::read_to_string("config.json")
        .expect("Config file missing"); // Environment issue!
    // ...
}
```

## Good Example
```rust
// Invariant: after insert, the key exists
fn cache_and_get(&mut self, key: String, value: Value) -> &Value {
    self.cache.insert(key.clone(), value);
    self.cache.get(&key)
        .expect("BUG: key must exist immediately after insert")
}

// Invariant: already validated upstream
fn process_validated(data: ValidatedData) -> Result<Output, ProcessError> {
    let value = data.required_field
        .expect("BUG: ValidatedData guarantees required_field is Some");
    // ...
}
```

## Notes
- A good `expect()` message starts with "BUG:" (or similar), states the invariant, and explains why it should hold — `.expect("failed")` or `.expect("should not be None")` gives future readers nothing to act on.
- A common safe pattern is "validate once, `expect()` after": run real validation in a constructor that returns `Result`, then any later access to the now-guaranteed field can `expect()` without risk, since the type itself proves the invariant.
- When `expect()` is wrong, the alternatives are: propagate with `?`/`map_err`, provide a default with `unwrap_or`/`unwrap_or_default`, or handle both cases explicitly with `match`.

## References
- [err-no-unwrap-prod](err-no-unwrap-prod.md)
- [err-result-over-panic](err-result-over-panic.md)
