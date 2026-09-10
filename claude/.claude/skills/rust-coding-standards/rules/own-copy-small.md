---
title: Implement Copy for Small, Simple Types
impact: MEDIUM
impactDescription: Removes explicit .clone() noise for cheap value types
tags: [ownership, copy, ergonomics, api-design]
---

# Implement Copy for Small, Simple Types [MEDIUM]

## Description
A type that implements `Copy` is implicitly duplicated on assignment or when passed by value, instead of being moved. This removes the need for explicit `.clone()` calls and makes small value types (points, ids, colors) far more ergonomic to use. For small types — generally up to about 16 bytes — copying bytes is as fast or faster than the bookkeeping a move requires, so there is no performance downside.

## Bad Example
```rust
// Small type without Copy - requires explicit clone on every use
#[derive(Clone, Debug)]
struct Point {
    x: f64,
    y: f64,
}

fn distance(p1: Point, p2: Point) -> f64 {
    ((p2.x - p1.x).powi(2) + (p2.y - p1.y).powi(2)).sqrt()
}

let origin = Point { x: 0.0, y: 0.0 };
let target = Point { x: 3.0, y: 4.0 };
let d1 = distance(origin.clone(), target.clone()); // Tedious
let d2 = distance(origin.clone(), target.clone()); // Every use needs clone
```

## Good Example
```rust
// Small type with Copy - implicit duplication
#[derive(Clone, Copy, Debug)]
struct Point {
    x: f64,
    y: f64,
}

fn distance(p1: Point, p2: Point) -> f64 {
    ((p2.x - p1.x).powi(2) + (p2.y - p1.y).powi(2)).sqrt()
}

let origin = Point { x: 0.0, y: 0.0 };
let target = Point { x: 3.0, y: 4.0 };
let d1 = distance(origin, target); // Implicitly copied
let d2 = distance(origin, target); // origin and target remain valid
```

## Notes
- A type can only implement `Copy` if every field is `Copy`, it has no custom `Drop` implementation, and it holds no heap-allocated data (`String`, `Vec`, `Box`, etc.) — the compiler enforces this.
- Size guideline: implement `Copy` freely up to ~16 bytes; between 17-64 bytes, benchmark if the type is used in a hot path; above ~64 bytes, prefer references or accept the explicit `.clone()`/move cost.
- Standard-library `Copy` types worth remembering: all primitives, shared references `&T` (note `&mut T` is never `Copy` — copying a mutable reference would alias it, so it is reborrowed instead), raw pointers, function pointers, tuples/arrays of `Copy` types, and `Option<T>` where `T: Copy`.

## References
- [own-clone-explicit](own-clone-explicit.md)
- [own-move-large](own-move-large.md)
