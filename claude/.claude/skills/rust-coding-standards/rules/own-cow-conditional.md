---
title: Use Cow for Conditional Ownership
impact: MEDIUM
impactDescription: Skips allocation on the common unmodified-input path
tags: [ownership, cow, performance, allocation]
---

# Use Cow for Conditional Ownership [MEDIUM]

## Description
`Cow<'a, T>` (Clone-on-Write) lets a function return either a borrowed reference or an owned value through a single type, cloning only when the data actually needs to be modified. It is the right tool whenever a function usually just returns its input unchanged but occasionally needs to transform it — avoiding an allocation on the common path while still supporting the rare path that needs one.

## Bad Example
```rust
// Always allocates, even when the input doesn't need modification
fn normalize_path(path: &str) -> String {
    if path.contains("//") {
        path.replace("//", "/") // Allocation needed
    } else {
        path.to_string() // Unnecessary allocation!
    }
}

fn format_error(code: u32) -> String {
    match code {
        404 => "Not Found".to_string(),      // Unnecessary!
        500 => "Internal Error".to_string(), // Unnecessary!
        _ => format!("Error {}", code),      // This one needs allocation
    }
}
```

## Good Example
```rust
use std::borrow::Cow;

// Only allocates when a change is actually needed
fn normalize_path(path: &str) -> Cow<'_, str> {
    if path.contains("//") {
        Cow::Owned(path.replace("//", "/")) // Allocate
    } else {
        Cow::Borrowed(path) // Zero-cost borrow
    }
}

// Static strings stay borrowed
fn format_error(code: u32) -> Cow<'static, str> {
    match code {
        404 => Cow::Borrowed("Not Found"),          // No allocation
        500 => Cow::Borrowed("Internal Error"),     // No allocation
        _ => Cow::Owned(format!("Error {}", code)), // Allocate only for unknown
    }
}
```

## Notes
- Reach for `Cow` when the code usually borrows but sometimes needs to own, especially in a hot path where avoiding allocations matters. Skip it when the function always needs owned data (just use the owned type) or always borrows (just use a reference) — `Cow` adds indirection that isn't worth it there.
- `Cow::to_mut()` clones the data into the owned variant on first mutation and returns a `&mut` to it; subsequent mutations on an already-owned `Cow` are free.
- Real-world precedent: ripgrep's `globset` crate returns `Cow<[u8]>` from its path-matching functions so that the common case (no path rewriting needed) never allocates.

## References
- [own-borrow-over-clone](own-borrow-over-clone.md)
- [own-clone-explicit](own-clone-explicit.md)
