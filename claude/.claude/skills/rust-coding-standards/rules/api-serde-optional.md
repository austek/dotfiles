---
title: Make Serde a Feature Flag, Not a Hard Dependency
impact: MEDIUM
impactDescription: Removes compile time and binary size for every user who doesn't need it
tags: [api-design, serde, feature-flags, dependencies]
---

# Make Serde a Feature Flag, Not a Hard Dependency [MEDIUM]

## Description
Not every consumer of a library needs serialization support, and a required `serde` dependency imposes its compile time and binary size on all of them regardless. Making it an optional feature flag lets users who need `Serialize`/`Deserialize` opt in explicitly, while everyone else pays nothing — consistent with Rust's general preference for minimal, opt-in dependencies over bundled defaults.

## Bad Example
```toml
# Cargo.toml — every user pays for serde, even those who never serialize
[dependencies]
serde = { version = "1.0", features = ["derive"] }
```
```rust
use serde::{Serialize, Deserialize};

#[derive(Serialize, Deserialize)]
pub struct Config {
    pub name: String,
}
```

## Good Example
```toml
# Cargo.toml
[dependencies]
serde = { version = "1.0", features = ["derive"], optional = true }

[features]
default = []
serde = ["dep:serde"]
```
```rust
// lib.rs — derive applies only when the feature is enabled
#[cfg_attr(feature = "serde", derive(serde::Serialize, serde::Deserialize))]
pub struct Config {
    pub name: String,
}

// Users opt in explicitly:
// my_crate = { version = "1.0", features = ["serde"] }
```

## Notes
- `dep:serde` in the feature definition (Cargo's namespaced-features syntax) is what actually makes `serde` optional — omitting it and just listing `serde = { optional = true }` without a matching `[features]` entry using `dep:serde` implicitly creates a same-named feature, which is the older, less explicit pattern.
- `#[cfg_attr(docsrs, doc(cfg(feature = "serde")))]` on the type documents, on docs.rs, exactly which feature unlocks the `Serialize`/`Deserialize` impls — without it, users reading generated docs see the derives with no indication they're conditional.
- Test both configurations explicitly: `cargo test` (feature off) and `cargo test --features serde` (feature on), or `cargo test --all-features` to cover every combination at once when multiple optional dependencies exist.
- A required `serde` dependency is the right call for a crate that *is* fundamentally about serialization (a JSON-schema library, a config-file parser) — the exception is when serde support is the point, not an add-on.
- The same optional-feature pattern extends cleanly to other serialization formats a type might support — `rkyv`, `borsh` — each behind its own feature flag and its own `#[cfg_attr(feature = "...", derive(...))]` line, so users pull in only the formats they actually use.

## References
- [api-common-traits](api-common-traits.md)
