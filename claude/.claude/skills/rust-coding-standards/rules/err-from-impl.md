---
title: Implement From for Error Conversions to Enable the Question-Mark Operator
impact: MEDIUM
impactDescription: Removes repeated .map_err() boilerplate at every call site
tags: [error-handling, from-trait, question-mark, ergonomics]
---

# Implement From for Error Conversions to Enable the Question-Mark Operator [MEDIUM]

## Description
The `?` operator automatically converts the error type it encounters using the `From` trait. Implementing `From<SourceError> for YourError` for each error type a function can produce lets `?` convert it silently, instead of every call site writing its own `.map_err(...)`. This keeps propagation code clean and makes error wrapping consistent throughout the codebase.

## Bad Example
```rust
#[derive(Debug)]
enum AppError {
    Io(std::io::Error),
    Parse(serde_json::Error),
}

fn load_config(path: &str) -> Result<Config, AppError> {
    let content = std::fs::read_to_string(path)
        .map_err(|e| AppError::Io(e))?;         // Manual conversion everywhere
    let config: Config = serde_json::from_str(&content)
        .map_err(|e| AppError::Parse(e))?;       // Repeated boilerplate
    Ok(config)
}
```

## Good Example
```rust
use thiserror::Error;

#[derive(Error, Debug)]
enum AppError {
    #[error("IO error: {0}")]
    Io(#[from] std::io::Error),       // Auto-generates the From impl
    #[error("Parse error: {0}")]
    Parse(#[from] serde_json::Error), // #[from] does the work
}

fn load_config(path: &str) -> Result<Config, AppError> {
    let content = std::fs::read_to_string(path)?; // Auto-converts
    let config: Config = serde_json::from_str(&content)?; // Clean!
    Ok(config)
}
```

## Notes
- `#[from]` (thiserror) generates both the `From` impl and wires up `#[source]` in one attribute; write a manual `impl From<E> for YourError` only when the conversion needs to look different from a plain wrap, or `#[from]` isn't available.
- `#[from]`/manual `From` can't add extra context (like a file path) during conversion — for that, use a struct variant with an explicit `.map_err(|source| YourError::ReadFailed { path, source })?`, or reach for `anyhow`'s `.with_context()` instead.
- Avoid a blanket `impl<E: std::error::Error> From<E> for AppError` — it conflicts with any other specific `From` impl on the same type and erases the concrete error type by stringifying it.

## References
- [err-thiserror-lib](err-thiserror-lib.md)
- [err-source-chain](err-source-chain.md)
- [err-question-mark](err-question-mark.md)
