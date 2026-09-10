---
title: Use ThinVec for Nullable Collections With Minimal Overhead
impact: LOW
impactDescription: Shrinks an empty/optional Vec field from 24 bytes to 8
tags: [memory, thinvec, layout, niche-optimization]
---

# Use ThinVec for Nullable Collections With Minimal Overhead [LOW]

## Description
`Vec<T>` is 24 bytes even when empty — pointer, length, and capacity are all stored inline regardless of content. `ThinVec<T>`, from Mozilla's `thin_vec` crate, is a single 8-byte pointer instead, storing length and capacity in a header alongside the heap allocation (or using a static empty sentinel when there's nothing to store). For structs with many optional or often-empty vector fields — tree nodes where most nodes are leaves, sparse per-entity attribute lists — this cuts per-field overhead by two-thirds and gives `Option<ThinVec<T>>` a free niche optimization that `Option<Vec<T>>` never gets.

## Bad Example
```rust
struct TreeNode {
    value: i32,
    // Every node pays 24 bytes for children, even leaves
    children: Vec<TreeNode>,  // Most nodes are leaves with an empty Vec
}

struct SparseData {
    // Option<Vec<T>> is still 24 bytes — Vec has no null-pointer niche
    tags: Option<Vec<String>>,
    metadata: Option<Vec<Metadata>>,
    // 48 bytes total for fields that are usually None
}
```

## Good Example
```rust
use thin_vec::ThinVec;

struct TreeNode {
    value: i32,
    // An empty ThinVec is just a null pointer — 8 bytes
    children: ThinVec<TreeNode>,
}

struct SparseData {
    // ThinVec's niche makes Option free: 8 bytes each, not 24
    tags: ThinVec<String>,
    metadata: ThinVec<Metadata>,
    // 16 bytes total, versus 48 for the Vec version
}
```

## Notes
- `size_of::<ThinVec<u8>>()` and `size_of::<Option<ThinVec<u8>>>()` are both 8 bytes — the empty state doubles as `None`'s niche, unlike `Vec`, which needs a separate discriminant for `Option`.
- The trade-off is indirection: length and capacity live on the heap behind the single pointer, so every `.len()` call follows a pointer that `Vec` would read directly from the stack — expect slightly slower iteration and length checks.
- Reach for `ThinVec` when a field is often empty and instances are numerous (sparse graph edges, optional document attachments); skip it for hot per-element iteration loops or for a handful of instances where the byte savings are meaningless.
- The API deliberately mirrors `Vec` (`push`, `extend`, `pop`, slicing, `Into`/`From` conversions both ways), so adopting it is close to a drop-in type change rather than a rewrite.
- Measure before switching — the win is purely memory footprint, and if cache locality of length/capacity on the stack matters more to your workload than per-instance size, `Vec` remains the better default.

## References
- [mem-smallvec](mem-smallvec.md)
- [mem-boxed-slice](mem-boxed-slice.md)
- [mem-with-capacity](mem-with-capacity.md)
