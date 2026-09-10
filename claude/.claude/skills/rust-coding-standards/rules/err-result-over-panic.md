---
title: Return Result Instead of Panicking for Recoverable Errors
impact: HIGH
impactDescription: Gives callers the choice to retry, fall back, or propagate
tags: [error-handling, result, panics, api-design]
---

# Return Result Instead of Panicking for Recoverable Errors [HIGH]

## Description
A panic unwinds the stack and, unhandled, crashes the thread or process — it removes any chance for the caller to recover. `Result<T, E>` instead hands the decision to the caller: retry, fall back to a default, log and continue, or propagate further up. Libraries should almost never panic on conditions the caller could plausibly hit (missing file, bad input, network failure); reserve panics for genuine bugs and truly unrecoverable situations.

## Bad Example
```rust
fn parse_config(path: &str) -> Config {
    let content = std::fs::read_to_string(path)
        .expect("Failed to read config"); // Crashes on a missing file
    serde_json::from_str(&content)
        .expect("Invalid config format")  // Crashes on bad JSON
}

fn divide(a: i32, b: i32) -> i32 {
    if b == 0 {
        panic!("Division by zero!"); // Crashes the program
    }
    a / b
}
// Caller has no chance to recover or provide a fallback.
```

## Good Example
```rust
use thiserror::Error;

#[derive(Error, Debug)]
enum ConfigError {
    #[error("failed to read config file: {0}")]
    Io(#[from] std::io::Error),
    #[error("invalid config format: {0}")]
    Parse(#[from] serde_json::Error),
}

fn parse_config(path: &str) -> Result<Config, ConfigError> {
    let content = std::fs::read_to_string(path)?;
    let config = serde_json::from_str(&content)?;
    Ok(config)
}

// Caller decides how to handle it
match parse_config("app.json") {
    Ok(config) => run_app(config),
    Err(e) => {
        eprintln!("Using default config: {}", e);
        run_app(Config::default())
    }
}
```

## Notes
- Panicking is still the right call for: violated internal invariants (`self.cache.get(key).expect("BUG: key was verified to exist")`), setup/initialization that genuinely can't proceed without succeeding, unreachable states (`unreachable!()`), and unimplemented paths (`unimplemented!()`).
- Library code should treat every input from a caller — including malformed data — as a `Result`, never a panic; only application code at the very top level (typically `main`) has license to panic on a truly fatal condition.
- Decision guide: file/network/parse errors and any failure caused by external or user-supplied data → `Result`; an internal invariant broken by the program's own logic → panic.

## References
- [err-thiserror-lib](err-thiserror-lib.md)
- [err-anyhow-app](err-anyhow-app.md)
- [err-no-unwrap-prod](err-no-unwrap-prod.md)
