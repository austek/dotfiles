---
title: Use Thiserror for Library Error Types
impact: MEDIUM
impactDescription: Minimal boilerplate for typed, matchable public errors
tags: [error-handling, thiserror, library, api-design]
---

# Use Thiserror for Library Error Types [MEDIUM]

## Description
Libraries should expose typed, matchable errors so callers can handle specific failure conditions instead of parsing strings. `thiserror` generates the `std::error::Error` trait implementation (`Display`, `source()`, and `From` where requested) from a plain enum annotated with `#[error("...")]` messages, giving you an ergonomic, matchable error type with almost none of the boilerplate a hand-written implementation requires.

## Bad Example
```rust
// String errors - not matchable
fn parse(input: &str) -> Result<Data, String> {
    Err("parse error".to_string())
}

// Manual implementation - verbose, easy to get wrong
#[derive(Debug)]
enum MyError {
    Io(std::io::Error),
    Parse(String),
}
impl std::fmt::Display for MyError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            MyError::Io(e) => write!(f, "io error: {}", e),
            MyError::Parse(s) => write!(f, "parse error: {}", s),
        }
    }
}
impl std::error::Error for MyError {
    fn source(&self) -> Option<&(dyn std::error::Error + 'static)> {
        match self {
            MyError::Io(e) => Some(e),
            MyError::Parse(_) => None,
        }
    }
}
```

## Good Example
```rust
use thiserror::Error;

#[derive(Error, Debug)]
pub enum ParseError {
    #[error("invalid syntax at line {line}: {message}")]
    Syntax { line: usize, message: String },
    #[error("unexpected end of file")]
    UnexpectedEof,
    #[error("io error reading input")]
    Io(#[from] std::io::Error), // Auto-generates From + source()
}

fn parse(input: &str) -> Result<Ast, ParseError> {
    if input.is_empty() {
        return Err(ParseError::UnexpectedEof);
    }
    // ...
}

match parse(input) {
    Ok(ast) => process(ast),
    Err(ParseError::Syntax { line, message }) => {
        eprintln!("Syntax error on line {}: {}", line, message);
    }
    Err(ParseError::UnexpectedEof) => eprintln!("File ended unexpectedly"),
    Err(e) => eprintln!("Error: {}", e),
}
```

## Notes
- Key attributes: `#[error("...")]` sets the `Display` message (interpolating tuple fields as `{0}` or named fields as `{field}`); `#[from]` both implements `From` and sets `source()`; `#[source]` sets `source()` alone, without generating `From`; `#[error(transparent)]` delegates both `Display` and `source()` straight to the wrapped error.
- Rule of thumb for the split: library public APIs use `thiserror` so callers get typed, matchable errors; application code uses `anyhow` for lower-ceremony error handling with context; a crate that's both a library and a binary often uses `thiserror` for its public API and `anyhow` internally.
- Every `#[source]`/`#[from]` field should implement `std::error::Error` (or be `anyhow::Error` for a transparent catch-all) so the resulting chain is walkable by callers and log formatters.

## References
- [err-anyhow-app](err-anyhow-app.md)
- [err-from-impl](err-from-impl.md)
- [err-source-chain](err-source-chain.md)
