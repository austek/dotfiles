---
title: Assert Type Sizes to Guard Against Silent Bloat
impact: LOW
impactDescription: Compile-time catch for accidental memory regressions
tags: [memory, static-assertion, size, compile-time]
---

# Assert Type Sizes to Guard Against Silent Bloat [LOW]

## Description
An enum or struct's size can grow silently when someone adds a field, and nothing in a normal diff review flags the memory impact. For types instantiated millions of times — events, AST nodes, cache entries — a few extra bytes per instance becomes megabytes at scale, with no compiler warning. A static size assertion (`const _: () = assert!(size_of::<T>() == N);`, or `static_assertions::assert_eq_size!`) turns an accidental size change into a compile error, forcing the change to be reviewed and the assertion updated deliberately.

## Bad Example
```rust
struct Event {
    timestamp: u64,
    kind: EventKind,
    payload: [u8; 32],
}

// Later, someone adds a field without realizing the impact
struct Event {
    timestamp: u64,
    kind: EventKind,
    payload: [u8; 32],
    metadata: String,  // Silently adds 24 bytes
}

// 10 million events now use hundreds of MB more memory —
// no warning, no review trigger
```

## Good Example
```rust
struct Event {
    timestamp: u64,
    kind: EventKind,
    payload: [u8; 32],
}

// No external crate needed (Rust 1.57+): breaks compilation if size changes
const _: () = assert!(
    std::mem::size_of::<Event>() == 48,
    "Event size changed — update this assertion after reviewing the memory impact"
);

// Or with the static_assertions crate for richer checks
use static_assertions::{assert_eq_size, const_assert};
assert_eq_size!(Event, [u8; 48]);
const_assert!(std::mem::align_of::<Event>() <= 8);
```

## Notes
- Place the assertion next to the type definition, not in a distant test file — it should be the first thing a size-increasing PR breaks.
- Give the `assert!` a custom message explaining *why* the size matters (cache-line budget, wire-protocol width, per-instance memory cap) so the next person knows whether to fix the type or update the constant.
- Reserve this for types that are hot (large collections, FFI/wire-format structs, per-instance-critical types) — asserting the size of a rarely-instantiated config struct adds friction with no payoff.
- Pair with `#[repr(C)]` for FFI/protocol types where layout, not just size, must stay fixed.
- A `#[cfg(test)]` test asserting sizes works too, but the `const _: ()` form fails the build itself rather than waiting for `cargo test`.

## References
- [mem-smaller-integers](mem-smaller-integers.md)
- [mem-box-large-variant](mem-box-large-variant.md)
- [static_assertions crate](https://docs.rs/static_assertions)
