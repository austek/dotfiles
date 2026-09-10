---
title: Use #[non_exhaustive] for Forward-Compatible Public Types
impact: HIGH
impactDescription: Lets you add variants/fields in a minor version without breaking callers
tags: [api-design, non-exhaustive, semver, evolution]
---

# Use #[non_exhaustive] for Forward-Compatible Public Types [HIGH]

## Description
Adding a variant to a public enum, or a field to a public struct, is normally a breaking change for any downstream code that matches exhaustively or uses struct-literal construction. `#[non_exhaustive]` forces external callers to include a wildcard arm in matches and forbids external struct-literal construction, which reserves your right to add variants or fields in a later minor version without breaking anyone who followed those constraints — a semver-safe extension point built into the type system.

## Bad Example
```rust
// Public enum — adding a variant is a breaking change
pub enum ErrorKind {
    NotFound,
    PermissionDenied,
}

// Downstream code with no wildcard — breaks the moment you add a variant
match error.kind() {
    ErrorKind::NotFound => ...,
    ErrorKind::PermissionDenied => ...,
    // No wildcard: adding ErrorKind::TimedOut later breaks this match
}
```

## Good Example
```rust
// Can add variants in minor versions
#[non_exhaustive]
pub enum ErrorKind {
    NotFound,
    PermissionDenied,
    // Future: TimedOut can be added here without a breaking change
}

// Downstream code MUST have a wildcard arm
match error.kind() {
    ErrorKind::NotFound => ...,
    ErrorKind::PermissionDenied => ...,
    _ => ...,  // Required by non_exhaustive
}

#[non_exhaustive]
pub struct Config {
    pub name: String,
}

impl Config {
    // External code must use a constructor instead of struct-literal syntax
    pub fn new(name: impl Into<String>) -> Self {
        Config { name: name.into() }
    }
}
```

## Notes
- `#[non_exhaustive]` only restricts *external* crates — code inside the defining crate can still exhaustively match or construct with struct-literal syntax, since the crate author already knows about every current variant.
- On a struct, external code retains read access to public fields; what it loses is `StructName { field: value }` construction — provide a `new()` or builder as the replacement construction path.
- `#[non_exhaustive]` can also be applied to a single enum variant with fields (`#[non_exhaustive] Error { code: u32, message: String }`), which requires external `..` in destructuring even while the enum itself stays exhaustively matchable.
- Best candidates: any public error enum, and configuration/options structs likely to grow. Skip it on types that are conceptually complete and stable — `std::cmp::Ordering`'s `Less`/`Equal`/`Greater` will never gain a fourth variant, so marking it `#[non_exhaustive]` would only add friction with no future benefit.
- This is a one-way door in the sense that removing `#[non_exhaustive]` later is itself a (minor, usually harmless) semver consideration — but adding it after the fact is *always* safe, since it only restricts what external code was already fragile in doing.

## References
- [api-sealed-trait](api-sealed-trait.md)
- [err-custom-type](err-custom-type.md)
- [api-builder-pattern](api-builder-pattern.md)
