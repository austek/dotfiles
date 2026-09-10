---
title: Implement Default for Types With Sensible Defaults
impact: MEDIUM
impactDescription: Unlocks unwrap_or_default, struct-update syntax, and generic Default bounds
tags: [api-design, default, ergonomics, traits]
---

# Implement Default for Types With Sensible Defaults [MEDIUM]

## Description
`Default` is the standard trait for producing a canonical instance of a type, and it powers several ecosystem patterns beyond a plain constructor: `Option::unwrap_or_default()`, struct-update syntax (`Config { retries: 5, ..Default::default() }`), and generic code bounded by `T: Default`. A custom `fn new() -> Self` constructor works for direct calls but is invisible to any of these patterns — implementing `Default` instead (or in addition, delegating `new` to it) makes the type a first-class citizen of generic and ergonomic Rust code.

## Bad Example
```rust
struct Config {
    timeout: Duration,
    retries: u32,
    verbose: bool,
}

impl Config {
    // Custom constructor — works, but invisible to Default-based patterns
    fn new() -> Self {
        Config { timeout: Duration::from_secs(30), retries: 3, verbose: false }
    }
}

let config: Config = Default::default();  // Error: Default not implemented
```

## Good Example
```rust
use std::time::Duration;

// Simple case: derive uses each field's own Default (Duration::ZERO, 0, false)
#[derive(Default)]
struct Simple {
    retries: u32,
    verbose: bool,
}

// Non-zero defaults require a manual impl
struct Config {
    timeout: Duration,
    retries: u32,
    verbose: bool,
}

impl Default for Config {
    fn default() -> Self {
        Config {
            timeout: Duration::from_secs(30),
            retries: 3,
            verbose: false,
        }
    }
}

// Now works with all standard patterns
let config = Config::default();
let config = Config { retries: 5, ..Default::default() };
let value = map.get("key").cloned().unwrap_or_default();
```

## Notes
- `#[derive(Default)]` uses each field's own `Default` implementation (`0` for integers, `false` for `bool`, `""` for `String`) — reach for a manual `impl Default` the moment any field needs a non-zero, non-empty canonical value.
- Don't implement `Default` when a field genuinely has no sensible default (a required `UserId`, say) — provide a `new(id: UserId, ...)` constructor instead, or a builder with `Default` on the *builder* rather than the final type.
- `PhantomData<T>` is `Default` for any `T`, so generic wrapper types holding only a `PhantomData` marker can derive `Default` unconditionally regardless of whether `T: Default`.
- Per-field non-zero defaults directly in the struct literal (`timeout: Duration = Duration::from_secs(30)`) require the nightly `default_field_values` feature — on stable, a manual `impl Default` is still the way to express this.
- Combine with the builder pattern by deriving `Default` on the builder struct itself, so `Builder::default()` (and therefore `Builder::new()`) needs no hand-written field initialization.

## References
- [api-builder-pattern](api-builder-pattern.md)
- [api-common-traits](api-common-traits.md)
- [api-from-not-into](api-from-not-into.md)
