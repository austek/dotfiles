---
title: Use clone_from to Reuse Allocations When Repeatedly Cloning
impact: MEDIUM
impactDescription: Avoids drop-then-reallocate churn in hot loops
tags: [memory, clone, allocation, loop]
---

# Use clone_from to Reuse Allocations When Repeatedly Cloning [MEDIUM]

## Description
`x = y.clone()` drops `x`'s existing allocation and creates a fresh one to hold `y`'s data. `x.clone_from(&y)` instead reuses `x`'s existing capacity when it's large enough, copying bytes in place rather than freeing and reallocating. For code that clones repeatedly into the same variable — buffers reused across loop iterations, fields overwritten on every update — this avoids allocator churn that `x = y.clone()` pays on every pass.

## Bad Example
```rust
let mut buffer = String::with_capacity(1024);

for source in &sources {
    buffer = source.clone();  // Drops old allocation, allocates new
    process(&buffer);
}
// Each iteration: drop buffer's allocation, then allocate again for the clone —
// allocator thrashing on every pass
```

## Good Example
```rust
let mut buffer = String::with_capacity(1024);

for source in &sources {
    buffer.clone_from(source);  // Reuses allocation if capacity is sufficient
    process(&buffer);
}
// If source.len() <= 1024, no allocation happens — just a copy into existing memory
```

## Notes
- `clone_from` is a method on the `Clone` trait with a default implementation of `*self = source.clone()`; the benefit only exists when a type overrides it to actually reuse capacity, as `String`, `Vec<T>`, `HashMap`, and `PathBuf` all do in std.
- When implementing `Clone` for a struct wrapping a `Vec` or `String`, override `clone_from` to delegate to the field's own `clone_from` — the default derive does not do this for you.
- There's no benefit for a single, one-off clone (nothing to reuse), for `Copy` types (no allocation involved), or in a context where you only have `&self` and can't call `clone_from` (which needs `&mut self`).
- Benchmark before assuming a win: for short-lived or write-once buffers the win typically doesn't materialize, but in tight loops reusing the same variable it commonly measures 2-3x faster than `clone()` for this narrow pattern.
- `Option::take()` combined with `mem::take` solves a related but different problem — moving a value out of a field rather than copying into one.

## References
- [mem-with-capacity](mem-with-capacity.md)
- [mem-reuse-collections](mem-reuse-collections.md)
- [own-clone-explicit](own-clone-explicit.md)
