---
title: Preserve Error Chains With #[source]
impact: MEDIUM
impactDescription: Keeps the full causal chain available to loggers and reporters
tags: [error-handling, source-chain, thiserror, debugging]
---

# Preserve Error Chains With #[source] [MEDIUM]

## Description
Errors frequently have an underlying cause. Preserving that chain — via the `#[source]` attribute (thiserror) or a manual `std::error::Error::source()` implementation — lets logging frameworks and error reporters walk the full causal path: "config parse failed → JSON syntax error at line 5 → unexpected token". Converting the source error into a `String` early (`e.to_string()`) throws that structure away permanently.

## Bad Example
```rust
#[derive(Debug)]
enum ConfigError {
    ParseFailed(String), // Lost the original serde_json::Error
}

fn load_config(path: &str) -> Result<Config, ConfigError> {
    let content = std::fs::read_to_string(path)
        .map_err(|e| ConfigError::ParseFailed(e.to_string()))?; // Chain lost!
    serde_json::from_str(&content)
        .map_err(|e| ConfigError::ParseFailed(e.to_string()))
}
// Error output: "Parse failed: invalid type: ..."
// Missing: which file? what line? what was the parent error?
```

## Good Example
```rust
use thiserror::Error;

#[derive(Error, Debug)]
enum ConfigError {
    #[error("failed to read config file '{path}'")]
    ReadFailed {
        path: String,
        #[source] // Preserves the error chain
        source: std::io::Error,
    },
    #[error("failed to parse config file '{path}'")]
    ParseFailed {
        path: String,
        #[source] // Original parse error preserved
        source: serde_json::Error,
    },
}

fn load_config(path: &str) -> Result<Config, ConfigError> {
    let content = std::fs::read_to_string(path)
        .map_err(|source| ConfigError::ReadFailed { path: path.to_string(), source })?;
    serde_json::from_str(&content)
        .map_err(|source| ConfigError::ParseFailed { path: path.to_string(), source })
}
```

## Notes
- Walk a chain manually with `let mut source = error.source(); while let Some(err) = source { ...; source = err.source(); }`, or rely on `anyhow`'s `{:?}` format, which prints the full chain (and backtrace) for you.
- `#[from]` implements `From` *and* sets `#[source]` in one step; use bare `#[source]` when a `From` impl would be wrong or ambiguous — for example when the same source error type needs to map to more than one variant depending on context.
- A manual `impl Error for MyError` needs its own `source()` method returning `self.source.as_ref().map(|e| e.as_ref() as &(dyn Error + 'static))` — `thiserror`'s `#[source]`/`#[from]` generate this for you.

## References
- [err-thiserror-lib](err-thiserror-lib.md)
- [err-context-chain](err-context-chain.md)
- [err-from-impl](err-from-impl.md)
