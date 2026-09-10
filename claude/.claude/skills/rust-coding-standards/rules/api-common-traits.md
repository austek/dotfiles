---
title: Implement Common Traits for Public Types
impact: HIGH
impactDescription: Unlocks debugging, comparison, and collection use with zero custom code
tags: [api-design, traits, debug, ergonomics]
---

# Implement Common Traits for Public Types [HIGH]

## Description
Standard traits — `Debug`, `Clone`, `PartialEq`, `Hash`, `Default` — make a type interoperable with the rest of the Rust ecosystem: `Debug` enables `{:?}` formatting and useful panic messages, `PartialEq` enables `assert_eq!` in tests, `Hash` + `Eq` let a type be a `HashMap` key. A bare public struct that derives none of these forces every downstream user to hit a compile error the first time they try to print it, compare it, or put it in a collection — friction that costs nothing to avoid with `#[derive(...)]`.

## Bad Example
```rust
// Bare struct — severely limited usability
pub struct Point {
    pub x: f64,
    pub y: f64,
}

println!("{:?}", point);        // Error: Debug not implemented
if point1 == point2 { }          // Error: PartialEq not implemented
let mut map: HashMap<Point, V> = HashMap::new();  // Error: Hash not implemented
```

## Good Example
```rust
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct Point {
    pub x: f64,
    pub y: f64,
}

println!("{:?}", point);
assert_eq!(point1, point2);
let copy = point;  // Copy, not just Clone

// For hashable ID types
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub struct UserId(u64);

let mut map: HashMap<UserId, User> = HashMap::new();
```

## Notes
- Minimum recommended baseline for any public type: `Debug, Clone, PartialEq`. Add `Eq, Hash` for `HashMap`/`HashSet` keys; `Ord, PartialOrd` for `BTreeMap` or sorting; `Default` to support `unwrap_or_default()`; `Copy` only for small, `Drop`-free value types.
- `Eq` requires no floating-point fields (NaN breaks reflexivity), and `Hash`'s implementation must stay consistent with `PartialEq` — hash equal values identically, or `HashMap` lookups silently break.
- Write manual `PartialEq`/`Hash`/`Debug` implementations when the derived behavior is wrong for the domain — case-insensitive string comparison, or redacting a `Password` field from `Debug` output (`write!(f, "Password([REDACTED])")`) rather than printing the secret.
- Bundle `Serialize, Deserialize` (behind a feature flag if this is a library — see `api-serde-optional`) alongside the common traits for any type that crosses a wire or file boundary.
- Deriving traits is nearly free at compile time and eliminates an entire category of "why can't I do X with this type" questions from API consumers — default to deriving generously rather than adding traits reactively as each missing one is discovered.

## References
- [own-copy-small](own-copy-small.md)
- [api-default-impl](api-default-impl.md)
