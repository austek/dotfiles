---
title: Use SmallVec for Usually-Small Collections
impact: MEDIUM
impactDescription: Eliminates heap allocation in the common small-size case
tags: [memory, smallvec, allocation, collections]
---

# Use SmallVec for Usually-Small Collections [MEDIUM]

## Description
`SmallVec<[T; N]>` stores up to `N` elements inline on the stack and only allocates on the heap once the collection grows past `N`. Many real-world collections — path components, function arguments, AST children, accumulated validation errors — are almost always small, with the occasional outlier. A plain `Vec` heap-allocates for every instance regardless of size; `SmallVec` eliminates that allocation for the common case while still supporting unbounded growth when it's genuinely needed.

## Bad Example
```rust
// Always heap-allocates, even for 1-2 elements
fn get_path_components(path: &str) -> Vec<&str> {
    path.split('/').collect()  // Usually 2-4 components
}

// Always heap-allocates for the error list, even when validation passes
fn validate(input: &Input) -> Vec<ValidationError> {
    let mut errors = Vec::new();  // Usually 0-3 errors
    errors
}
```

## Good Example
```rust
use smallvec::{smallvec, SmallVec};

// Stack-allocated for typical paths (1-8 components)
fn get_path_components(path: &str) -> SmallVec<[&str; 8]> {
    path.split('/').collect()
}

// Stack-allocated for the typical error count
fn validate(input: &Input) -> SmallVec<[ValidationError; 4]> {
    let mut errors = SmallVec::new();
    errors
}

let v: SmallVec<[i32; 4]> = smallvec![1, 2, 3];
```

## Notes
- Choose `N` from the actual distribution of your data, not a guess — measure typical sizes (path depth, argument counts, error rates) before picking the inline capacity.
- `SmallVec<[T; N]>` is itself larger than `Vec<T>` (inline storage plus a discriminant) and every operation branches on whether storage is inline or spilled, so it is not a free lunch — profile before adopting on a path that is not allocation-bound.
- Decision table: usually small but sometimes large → `SmallVec<[T; N]>`; always small with a hard maximum → `ArrayVec<T, N>`; rarely grows past an initial size → plain `Vec::with_capacity`; no `unsafe` allowed anywhere in the dependency tree → `TinyVec`; often empty → `ThinVec`.
- `TinyVec` implements the same idea as `SmallVec` using 100% safe code, at a small performance cost, for codebases that forbid `unsafe` dependencies.
- rust-analyzer and rustc itself use `SmallVec` extensively for small, hot collections like macro expansion output — a strong signal for where the pattern pays off in real compilers and language tools.

## References
- [mem-arrayvec](mem-arrayvec.md)
- [mem-with-capacity](mem-with-capacity.md)
- [mem-thinvec](mem-thinvec.md)
