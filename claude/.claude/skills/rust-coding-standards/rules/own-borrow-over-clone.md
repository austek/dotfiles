---
title: Prefer Borrowing Over Cloning
impact: HIGH
impactDescription: Eliminates unnecessary allocations, often 2-10x faster in hot paths
tags: [ownership, borrowing, performance, clone]
---

# Prefer Borrowing Over Cloning [HIGH]

## Description
Cloning allocates new memory and copies data; borrowing is free. When a function only needs to read data, accept a reference (`&T`, `&str`, `&[T]`) instead of cloning it or requiring an owned value. Unnecessary clones compound badly in loops and hot paths, where each iteration pays for an allocation and copy that borrowing would avoid entirely.

## Bad Example
```rust
fn process(data: &String) {
    let local = data.clone(); // Unnecessary allocation!
    println!("{}", local);
}

fn count_words(text: &String) -> usize {
    let owned = text.clone(); // Why clone just to read?
    owned.split_whitespace().count()
}

fn process_all(items: &[String]) {
    for item in items {
        let copy = item.clone(); // N allocations!
        handle(&copy);
    }
}
```

## Good Example
```rust
fn process(data: &str) { // Accept &str, more flexible
    println!("{}", data); // No allocation needed
}

fn count_words(text: &str) -> usize {
    text.split_whitespace().count() // Just borrow
}

fn process_all(items: &[String]) {
    for item in items {
        handle(item); // Pass reference, zero allocations
    }
}
```

## Notes
- Clone is still the right call in specific cases: when you need to store owned data (e.g. inserting into a `HashMap`), when data must cross a thread boundary and needs `'static` lifetime, or for `Copy` types where "cloning" is just a cheap bitwise copy.
- `x.clone()` where `x: i32` (or another `Copy` type) is not a heap allocation — the cost concern is specific to heap-backed types like `String`, `Vec`, and `Box`.
- Reference: ripgrep's `globset` crate borrows through `Cow` in its path-matching hot path instead of cloning path segments, precisely to avoid allocation in a function called per file scanned.

## References
- [own-slice-over-vec](own-slice-over-vec.md)
- [own-cow-conditional](own-cow-conditional.md)
- [own-lifetime-elision](own-lifetime-elision.md)
