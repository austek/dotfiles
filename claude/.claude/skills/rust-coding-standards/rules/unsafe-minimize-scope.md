---
title: Keep unsafe Blocks as Small as Possible
impact: HIGH
impactDescription: Isolates exactly which operation needs auditing
tags: [unsafe, scope, rust-2024, review]
---

# Keep unsafe Blocks as Small as Possible [HIGH]

## Description
When an entire function is marked `unsafe fn`, every line inside reads as equally suspect to an auditor, even the arithmetic and bounds checks that are perfectly safe. Shrinking `unsafe` blocks to the minimum necessary isolates exactly which single operation actually violates Rust's safety invariants, which makes review tractable and bugs far easier to spot. Rust 2024 enforces the same discipline mechanically with `unsafe_op_in_unsafe_fn`: an unsafe operation inside an `unsafe fn` body now needs its own explicit `unsafe {}` rather than inheriting unsafety from the function signature.

## Bad Example
```rust
// Entire body marked unsafe — safe arithmetic, a bounds check, and the
// one actually unsafe dereference all look equally dangerous to a reader.
unsafe fn sum_at(ptr: *const i32, len: usize, index: usize) -> i32 {
    let adjusted_len = len.saturating_sub(1); // safe — but looks unsafe
    assert!(index <= adjusted_len);           // safe — but looks unsafe
    let value = *ptr.add(index);              // the only actually unsafe op
    value + 1
}
```

## Good Example
```rust
// Safe wrapper: the single unsafe operation is clearly isolated.
fn sum_at(ptr: *const i32, len: usize, index: usize) -> i32 {
    assert!(index < len, "index out of bounds");
    // SAFETY: index < len guarantees ptr.add(index) is within the allocation.
    let value = unsafe { *ptr.add(index) };
    value + 1
}

/// # Safety
///
/// `ptr` must be valid for reads for `len` bytes and properly aligned.
pub unsafe fn process(ptr: *const u8, len: usize) -> Vec<u8> {
    let mut result = Vec::with_capacity(len); // safe — outside any unsafe block
    for i in 0..len {
        // SAFETY: caller guarantees ptr is valid for len bytes; i < len.
        let byte = unsafe { *ptr.add(i) };
        result.push(byte);
    }
    result
}
```

## Notes
- Under Rust 2024's `unsafe_op_in_unsafe_fn`, even inside an `unsafe fn`, each unsafe operation needs its own `unsafe {}` block — this is a hard compile error, not a lint warning, under the 2024 edition.
- A safe wrapper function around one small `unsafe {}` block is almost always preferable to exposing the whole function as `unsafe fn` — it narrows what callers must reason about to nothing at all.
- Every small unsafe block still needs its own `// SAFETY:` comment explaining why that specific operation is sound at that call site.
- A single block covering multiple lines is acceptable only when every line shares the exact same precondition and separating them would just repeat the identical justification — otherwise, split it.

## References
- [unsafe-safety-comment](unsafe-safety-comment.md)
- [unsafe-send-sync-manual](unsafe-send-sync-manual.md)
