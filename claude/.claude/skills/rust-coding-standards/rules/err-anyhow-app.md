---
title: Use Anyhow for Application Error Handling
impact: MEDIUM
impactDescription: Cuts error-handling boilerplate in application/CLI code
tags: [error-handling, anyhow, application, ergonomics]
---

# Use Anyhow for Application Error Handling [MEDIUM]

## Description
Applications often don't need typed, matchable errors — they need to report what went wrong with good context and get out. `anyhow::Error` wraps any error type, chains context with `.context()`/`.with_context()`, and captures backtraces, without requiring a hand-rolled error enum for every call site. Reserve typed errors (`thiserror`) for library public APIs; use `anyhow` in the application/binary layer that consumes them.

## Bad Example
```rust
// Tedious type management, every call site returns a different error type
fn load_config() -> Result<Config, Box<dyn std::error::Error>> {
    let path = find_config()?;                       // Returns FindError
    let content = std::fs::read_to_string(&path)?;    // Returns io::Error
    let config: Config = toml::from_str(&content)?;   // Returns toml::Error
    validate(&config)?;                               // Returns ValidationError
    Ok(config)
}

// No context - hard to debug which step failed
fn process() -> Result<(), Box<dyn std::error::Error>> {
    let data = fetch()?;   // Which fetch failed?
    transform(data)?;      // What was being transformed?
    save()?;               // Where was it saving to?
    Ok(())
}
```

## Good Example
```rust
use anyhow::{Context, Result};

fn load_config() -> Result<Config> {
    let path = find_config()
        .context("failed to locate config file")?;
    let content = std::fs::read_to_string(&path)
        .with_context(|| format!("failed to read config from {}", path.display()))?;
    let config: Config = toml::from_str(&content)
        .context("failed to parse config as TOML")?;
    validate(&config)
        .context("config validation failed")?;
    Ok(config)
}
// Error message: "config validation failed: field 'port' must be > 0"
// Full chain preserved for debugging

fn main() -> Result<()> {
    let config = load_config()?;
    run_app(config)?;
    Ok(())
}
```

## Notes
- `anyhow!("...")` builds an ad-hoc error, `bail!("...")` returns early with one, and `ensure!(cond, "...")` asserts a condition and returns an error if it fails — all lighter-weight than defining a variant for a one-off failure.
- Combine the two crates deliberately: define typed variants with `thiserror` in the library, consume them with `anyhow::Context` in the application; `err.downcast_ref::<ApiError>()` recovers the concrete type from an `anyhow::Error` when the caller needs to match on it.
- Print `{}` for the top message, `{:#}` for the full cause chain inline, or `{:?}` for the chain plus backtrace (when `RUST_BACKTRACE=1`).

## References
- [err-thiserror-lib](err-thiserror-lib.md)
- [err-context-chain](err-context-chain.md)
