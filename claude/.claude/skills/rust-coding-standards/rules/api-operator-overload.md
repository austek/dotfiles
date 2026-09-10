---
title: Overload Operators Only When Semantics Are Obvious
impact: MEDIUM
impactDescription: Prevents surprising side effects from hiding behind familiar syntax
tags: [api-design, operators, traits, ergonomics]
---

# Overload Operators Only When Semantics Are Obvious [MEDIUM]

## Description
Rust allows operator overloading through `std::ops` traits (`Add`, `Sub`, `Mul`, `Index`, `Neg`), and the Rust API Guidelines (C-OVERLOAD) permit it — but only when the meaning is immediately obvious to any reader with no domain-specific knowledge. Natural fits: arithmetic on a numeric newtype, vector or matrix math, set union/intersection via `|`/`&`. A surprising overload — `+` that mutates hidden state, `*` that performs a network call, `Index` that panics unconditionally on invalid input — misleads readers who bring ordinary arithmetic expectations to familiar syntax. When the mapping isn't obvious, name a method instead.

## Bad Example
```rust
use std::ops::Add;

struct Logger(Vec<String>);

// Anti-pattern: + mutates internal state and has a side effect
impl Add<String> for Logger {
    type Output = Logger;
    fn add(mut self, msg: String) -> Logger {
        self.0.push(msg.clone());
        println!("logged: {msg}");  // Side effect hidden behind `+`
        self
    }
}
```

## Good Example
```rust
use std::ops::Add;

#[derive(Debug, Clone, Copy, PartialEq)]
struct Vector2 { x: f64, y: f64 }

// Add for owned values
impl Add for Vector2 {
    type Output = Vector2;
    fn add(self, rhs: Vector2) -> Vector2 {
        Vector2 { x: self.x + rhs.x, y: self.y + rhs.y }
    }
}

// Also implement for references — avoids forcing callers to clone
impl Add for &Vector2 {
    type Output = Vector2;
    fn add(self, rhs: &Vector2) -> Vector2 {
        Vector2 { x: self.x + rhs.x, y: self.y + rhs.y }
    }
}

let a = Vector2 { x: 1.0, y: 2.0 };
let b = Vector2 { x: 3.0, y: 4.0 };
let c = a + b;    // owned
let d = &a + &b;  // borrowed — no clone needed
```

## Notes
- Decision guide: arithmetic on a numeric or geometric newtype, set operations (`|` union, `&` intersection), `Index`/`IndexMut` on a container that genuinely holds indexable items — implement. An operator with visible side effects, or whose meaning depends on context the type alone doesn't capture — never; name a method instead.
- Always implement the matching compound-assignment trait (`AddAssign` alongside `Add`, `SubAssign` alongside `Sub`) — a type with `+` but not `+=` is an incomplete, surprising API.
- Implement both the owned form (`impl Add for Vector2`) and the reference form (`impl Add for &Vector2`) so callers aren't forced to clone just to add two values they still need afterward.
- Real numeric types often need multiple right-hand-side types for the same operator — `Mul<f64> for Vector2` (scalar multiply) alongside `Mul<Vector2> for Vector2` (dot or component-wise product) is a normal, expected pattern, not overloading gone too far.
- `Index`/`IndexMut` should panic only for genuinely invalid indices, exactly as `Vec`'s own `Index` does — an `Index` impl that panics on *valid* input surprises callers who reasonably modeled it on the standard collection types.

## References
- [api-common-traits](api-common-traits.md)
- [api-newtype-safety](api-newtype-safety.md)
