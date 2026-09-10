---
title: Mark Types and Functions #[must_use] When Ignoring Them Is a Bug
impact: MEDIUM
impactDescription: Converts silently-discarded results into compiler warnings
tags: [api-design, must-use, ergonomics, correctness]
---

# Mark Types and Functions #[must_use] When Ignoring Them Is a Bug [MEDIUM]

## Description
Some return values must never be silently discarded — a `Result` that might be an error, a lock guard whose only purpose is to be held, a computed value from a function with no side effects at all. Without `#[must_use]`, ignoring any of these compiles without a hint, and the bug (an unhandled error, an instantly-released lock, a pointless computation) surfaces only at runtime, if it surfaces at all. `#[must_use]` — on a function, or on a type so every function returning it inherits the warning — makes the compiler flag the mistake at the call site instead.

## Bad Example
```rust
// Result ignored — error silently dropped, caller never finds out
fn send_email(to: &str, body: &str) -> Result<(), EmailError> { ... }

send_email("user@example.com", "Hello!");  // No warning if Result ignored!
```

## Good Example
```rust
#[must_use = "this `Result` may be an `Err` that should be handled"]
fn send_email(to: &str, body: &str) -> Result<(), EmailError> { ... }

send_email("user@example.com", "Hello!");
// Warning: unused `Result` that must be used

// Mark RAII guards and lazy types too
#[must_use = "if unused, the lock will be immediately released"]
struct MutexGuard<'a, T> { ... }

#[must_use = "iterators are lazy and do nothing unless consumed"]
struct Map<I, F> { ... }
```

## Notes
- Apply `#[must_use]` to a type itself (not just individual functions) when every value of that type should be used — RAII guards, futures, custom `Result`-like enums — so every function returning it inherits the warning automatically.
- Write a message, not a bare attribute: `#[must_use = "..."]` tells the reader what to do about the warning, while a bare `#[must_use]` only tells them something is wrong.
- Good candidates: pure functions with no side effects, fallible operations returning `Result`/`Option`, builder methods returning `Self`, and lazy types like iterators and futures that do nothing until driven. Poor candidates: functions whose entire purpose is a side effect (`Vec::push`, most logging calls) where the return value, if any, is genuinely optional to inspect.
- `clippy::unused_must_use = "deny"` (built into Clippy) turns the warning into a hard error; `clippy::must_use_candidate = "warn"` suggests places where the attribute is missing but would help.
- `Result<T, E>` and `Option<T>` are already `#[must_use]` in the standard library — this rule extends the same discipline to your own fallible and lazy types rather than inventing a new pattern.

## References
- [api-builder-must-use](api-builder-must-use.md)
- [err-result-over-panic](err-result-over-panic.md)
