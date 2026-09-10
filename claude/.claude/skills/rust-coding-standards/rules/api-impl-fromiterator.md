---
title: Implement FromIterator, Extend, and IntoIterator for Collection Types
impact: MEDIUM
impactDescription: Unlocks collect(), extend(), and for loops on custom collections
tags: [api-design, collections, iterator, traits]
---

# Implement FromIterator, Extend, and IntoIterator for Collection Types [MEDIUM]

## Description
The Rust API Guidelines (C-COLLECT) expect a collection type to implement `FromIterator<T>` so `iter.collect::<MyCollection<T>>()` works, and pairing it with `Extend<T>` enables efficient batch insertion — `collect` itself uses `Extend` internally when growing an existing collection. Implementing `IntoIterator` for the owned type, `&Type`, and `&mut Type` completes the contract, letting the collection participate in `for` loops and iterator adapter chains in all three access modes. Skipping any of these traits forces callers into manual loops and breaks generic code written against the standard collection contract.

## Bad Example
```rust
struct Bag<T>(Vec<T>);

impl<T> Bag<T> {
    fn new() -> Self { Bag(Vec::new()) }
    fn push(&mut self, item: T) { self.0.push(item); }
}

fn main() {
    // No collect(), no extend(), no for loop — callers must loop manually
    let mut b = Bag::new();
    for x in [1, 2, 3] {
        b.push(x);
    }
}
```

## Good Example
```rust
struct Bag<T>(Vec<T>);

// FromIterator — enables .collect::<Bag<T>>()
impl<T> FromIterator<T> for Bag<T> {
    fn from_iter<I: IntoIterator<Item = T>>(iter: I) -> Self {
        Bag(iter.into_iter().collect())
    }
}

// Extend — enables .extend(iter), also used internally by collect
impl<T> Extend<T> for Bag<T> {
    fn extend<I: IntoIterator<Item = T>>(&mut self, iter: I) {
        self.0.extend(iter);
    }
}

// IntoIterator for &Bag — enables `for x in &bag`
impl<'a, T> IntoIterator for &'a Bag<T> {
    type Item = &'a T;
    type IntoIter = std::slice::Iter<'a, T>;
    fn into_iter(self) -> Self::IntoIter {
        self.0.iter()
    }
}

fn main() {
    let b: Bag<i32> = [1, 2, 3].into_iter().collect();  // collect works
    let mut b2 = Bag::new();
    b2.extend([4, 5, 6]);                                // extend works
    for x in &b { let _ = x; }                           // for loop works
}
```

## Notes
- Implement all three `IntoIterator` forms — owned (`impl IntoIterator for Bag<T>`), shared-borrow (`&'a Bag<T>`), and mutable-borrow (`&'a mut Bag<T>`) — since generic code and `for` loops may need any of the three, and providing only one is a common source of "why won't this compile" reports from users.
- If your collection wraps an existing standard container, delegate `from_iter` and `extend` to the inner container's own implementations rather than reimplementing the logic — this is both simpler and preserves whatever internal optimizations the wrapped type already has.
- `FromIterator` combined with `Extend` lets `collect()` call `extend` on a pre-allocated collection when the iterator's `size_hint` permits it, avoiding intermediate allocations that a naive `from_iter` loop would otherwise incur.
- A type implementing this full contract composes transparently with `.map()`, `.filter()`, and `.collect()` chains — `b.into_iter().map(|x| x * 2).collect::<Bag<i32>>()` just works, with no special-casing anywhere in the chain.

## References
- [api-common-traits](api-common-traits.md)
