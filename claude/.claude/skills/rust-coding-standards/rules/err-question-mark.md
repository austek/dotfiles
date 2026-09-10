---
title: Use the Question-Mark Operator for Clean Propagation
impact: MEDIUM
impactDescription: Replaces verbose match/unwrap chains with a single character
tags: [error-handling, question-mark, ergonomics, propagation]
---

# Use the Question-Mark Operator for Clean Propagation [MEDIUM]

## Description
The `?` operator is Rust's idiomatic way to propagate a `Result` (or `Option`) error out of the current function. It's concise, keeps the success path readable, and automatically converts between compatible error types via `From` — replacing a verbose `match` (or, worse, an `unwrap()`) with a single trailing character.

## Bad Example
```rust
// Verbose match-based error handling
fn load_config() -> Result<Config, Error> {
    let content = match std::fs::read_to_string("config.toml") {
        Ok(c) => c,
        Err(e) => return Err(Error::Io(e)),
    };
    let config = match toml::from_str(&content) {
        Ok(c) => c,
        Err(e) => return Err(Error::Parse(e)),
    };
    Ok(config)
}
```

## Good Example
```rust
fn load_config() -> Result<Config, Error> {
    let content = std::fs::read_to_string("config.toml")?;
    let config = toml::from_str(&content)?;
    Ok(config)
}
```

## Notes
- `expr?` expands roughly to `match expr { Ok(val) => val, Err(err) => return Err(From::from(err)) }` — the `From::from` call is what lets `?` convert a lower-level error into the function's own error type automatically, as long as a `From` impl exists (see the from-impl rule).
- `?` also works on `Option<T>` inside a function returning `Option`, short-circuiting to `None` — handy for chained lookups like `text.lines().next()?.split_whitespace().next()?`.
- `fn main() -> Result<(), Box<dyn std::error::Error>>` lets `main` itself use `?`, which is often simpler than manually matching and calling `std::process::exit` on failure.

## References
- [err-context-chain](err-context-chain.md)
- [err-from-impl](err-from-impl.md)
- [err-anyhow-app](err-anyhow-app.md)
