---
title: Document Every unsafe Block With a SAFETY Comment
impact: CRITICAL
impactDescription: The only way a reviewer can verify unsafe code is sound
tags: [unsafe, safety, documentation, review]
---

# Document Every unsafe Block With a SAFETY Comment [CRITICAL]

## Description
An unsafe block is unauditable without justification — a reviewer cannot verify invariants they cannot read. Two distinct forms of documentation are both required, not either-or: a `# Safety` doc section on every `unsafe fn` describing the *caller's* obligations (what must hold for the call to be sound), and a `// SAFETY:` inline comment above every `unsafe {}` block explaining why *this specific operation*, at this specific call site, upholds those invariants. `clippy::undocumented_unsafe_blocks` enforces the inline form mechanically, and the standard library, tokio, and bevy all require both before merging unsafe code.

## Bad Example
```rust
// unsafe fn with no # Safety section — the caller has no idea what's required
pub unsafe fn read_at(ptr: *const u8, offset: usize) -> u8 {
    // no SAFETY comment — why is this dereference sound?
    unsafe { *ptr.add(offset) }
}
```

## Good Example
```rust
/// Returns the byte at `ptr + offset`.
///
/// # Safety
///
/// - `ptr` must be valid for reads for at least `offset + 1` bytes.
/// - `ptr` must not be null and must be properly aligned for `u8`.
/// - The memory must not be mutated for the duration of this call.
pub unsafe fn read_at(ptr: *const u8, offset: usize) -> u8 {
    // SAFETY: caller guarantees ptr is valid for at least offset + 1 bytes,
    // so ptr.add(offset) is in bounds and dereferenceable.
    unsafe { *ptr.add(offset) }
}

fn process(slice: &[u8]) -> Option<u8> {
    if slice.len() > 10 {
        // SAFETY: we just checked slice has at least 11 elements,
        // so index 10 is within bounds.
        Some(unsafe { *slice.as_ptr().add(10) })
    } else {
        None
    }
}
```

## Notes
- The `# Safety` doc section and the `// SAFETY:` inline comment target different audiences: the doc section is for *callers* deciding whether it's sound to call the function; the inline comment is for *auditors* verifying the implementation upholds those obligations internally.
- Enable `#![warn(clippy::undocumented_unsafe_blocks)]` explicitly so a missing `// SAFETY:` comment fails CI rather than relying on manual review to catch the omission.
- When one unsafe block spans multiple operations, write a single `// SAFETY:` comment addressing each distinct invariant, or split into several smaller blocks so each justification stays focused — see the companion rule on minimizing unsafe scope.
- Under Rust 2024's `unsafe_op_in_unsafe_fn`, an `unsafe fn` body still needs `// SAFETY:` comments on each inner `unsafe {}` block — the function-level `# Safety` doc does not substitute for per-operation justification inside the body.
- A comment that merely restates the code ("SAFETY: this is unsafe because we dereference a pointer") is not documentation — it must state the invariant being relied on and why it holds at this call site.

## References
- [unsafe-minimize-scope](unsafe-minimize-scope.md)
