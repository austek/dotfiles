---
title: Start Error Messages Lowercase, No Trailing Punctuation
impact: LOW
impactDescription: Clean composition when errors are chained or logged
tags: [error-handling, style, conventions, messages]
---

# Start Error Messages Lowercase, No Trailing Punctuation [LOW]

## Description
Error messages are routinely chained, logged, or displayed alongside other context. A consistent format — lowercase start, no trailing period — composes cleanly: `"failed to load config: invalid JSON: unexpected token"`. Mixed capitalization and stray punctuation produce awkward, sentence-like fragments when concatenated: `"Failed to load config.: Invalid JSON.: Unexpected token."`.

## Bad Example
```rust
use thiserror::Error;

#[derive(Error, Debug)]
enum ConfigError {
    #[error("Failed to read config file.")] // Capital F, trailing period
    ReadFailed(#[from] std::io::Error),
    #[error("Invalid JSON format!")]        // Capital I, exclamation
    ParseFailed(#[from] serde_json::Error),
}
// Chained output: "Config load error: Failed to read config file.: No such file"
```

## Good Example
```rust
use thiserror::Error;

#[derive(Error, Debug)]
enum ConfigError {
    #[error("failed to read config file")]  // lowercase, no period
    ReadFailed(#[from] std::io::Error),
    #[error("key not found: {0}")]          // lowercase, data at end
    KeyNotFound(String),
}
// Chained output: "config load error: failed to read config file: no such file"
// Clean, consistent
```

## Notes
- The standard library follows this convention throughout: `"entity not found"`, `"permission denied"`, `"invalid digit found in string"`, `"invalid utf-8 sequence"` — none capitalized, none punctuated.
- Proper nouns and acronyms keep their natural case even at the start of a lowercase message: `"invalid JSON syntax"`, `"OAuth token expired"`, `"HTTP request failed"`.
- The convention governs `Display` output (what users and logs see); `Debug` output for developers can carry more structure and detail without needing to follow this rule.

## References
- [err-thiserror-lib](err-thiserror-lib.md)
- [err-context-chain](err-context-chain.md)
