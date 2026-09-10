---
title: Avoid format! When a String Literal Works
impact: MEDIUM
impactDescription: Eliminates unnecessary heap allocations in hot paths
tags: [memory, allocation, format, hot-path]
---

# Avoid format! When a String Literal Works [MEDIUM]

## Description
`format!()` always allocates a new `String`, even when the text is entirely constant. Called in a loop or on a hot path, each of those allocations adds real allocator pressure for no benefit — the result never varies. Prefer a `&'static str` literal, pass format arguments directly to the consumer (a logging macro, `write!`), or return `Cow<'static, str>` when the value is sometimes static and sometimes computed.

## Bad Example
```rust
// Allocates every call, even for static text
fn get_error_message() -> String {
    format!("An error occurred")  // Unnecessary allocation
}

// Allocates in a loop before the logger even needs it
for item in items {
    log::info!("{}", format!("Processing item: {}", item));  // Double work
}

// format! in a hot classification path
fn classify(n: i32) -> String {
    if n > 0 { format!("positive") }
    else if n < 0 { format!("negative") }
    else { format!("zero") }
}
```

## Good Example
```rust
// Return &'static str for constants — no allocation
fn get_error_message() -> &'static str {
    "An error occurred"
}

// Pass format args directly; the logging macro formats without an
// intermediate String
for item in items {
    log::info!("Processing item: {}", item);
}

// Return Cow when the result is sometimes static, sometimes owned
use std::borrow::Cow;

fn classify(n: i32) -> Cow<'static, str> {
    match n {
        n if n > 0 => Cow::Borrowed("positive"),
        n if n < 0 => Cow::Borrowed("negative"),
        _ => Cow::Borrowed("zero"),
    }
}
```

## Notes
- Use `write!()` to format directly into an existing buffer instead of allocating a throwaway `String` with `format!()` just to push it onto another buffer.
- Building a message from many parts in a loop with `result = format!("{}{}", result, part)` reallocates on every iteration — pre-allocate with `String::with_capacity` or use `.join()` instead.
- `format!()` is fine on genuinely cold paths (startup logging, error construction after the fast path has already failed) where clarity outweighs a single allocation.
- `compact_str::format_compact!` produces a `CompactString` that stays on the stack for short results, avoiding the heap allocation entirely for common cases.
- When a function must return an owned `String` regardless (e.g. a public API contract), `format!()` is the correct, simplest choice — don't contort code to avoid it where an allocation is unavoidable anyway.

## References
- [mem-write-over-format](mem-write-over-format.md)
- [mem-with-capacity](mem-with-capacity.md)
- [own-cow-conditional](own-cow-conditional.md)
