---
title: Use Compact String Types for Memory-Constrained Storage
impact: LOW
impactDescription: Inline storage eliminates heap allocations for short strings
tags: [memory, string, compact-str, allocation]
---

# Use Compact String Types for Memory-Constrained Storage [LOW]

## Description
Standard `String` is 24 bytes of metadata (pointer, length, capacity) plus a separate heap allocation for every instance, regardless of content length. For workloads holding millions of short strings — usernames, tags, interned identifiers — that per-instance heap allocation dominates both memory use and allocator pressure. Compact string crates like `compact_str`, `smartstring`, and `ecow` store short strings inline within the same footprint as `String`, falling back to the heap only when a string exceeds the inline capacity.

## Bad Example
```rust
struct User {
    id: u64,
    // Most usernames are under 24 chars, but String always heap-allocates
    username: String,
    email: String,
}

// 1 million users: heap allocations for every username and email,
// plus 24 bytes of String metadata each — even for a 5-character name
```

## Good Example
```rust
use compact_str::CompactString;

struct User {
    id: u64,
    // Strings <= 23 bytes are stored inline — no heap allocation
    username: CompactString,
    email: CompactString,
}

// Most usernames fit inline: zero heap allocations for the common case,
// same 24-byte footprint as String, automatic heap fallback for longer values
let small: CompactString = "hello".into();      // Inline, no allocation
let large: CompactString = "x".repeat(100).into(); // Falls back to heap
```

## Notes
- `compact_str::CompactString` is a drop-in `String` alternative with the same 24-byte size but 23 bytes of inline capacity (the 24th byte encodes a length tag); `ecow::EcoString` is smaller still, at 16 bytes, and clones in O(1) via copy-on-write sharing.
- Reach for a compact string type when a struct is instantiated at scale and most values are short — a dictionary of words, a list of tags, template fragments.
- Avoid them at public API boundaries: accepting `CompactString` in a public function signature forces the crate dependency on every caller; accept `impl Into<String>` or `&str` there instead, and convert internally if needed.
- Avoid them in hot string-manipulation code — the inline/heap branch on every operation adds overhead that a plain `String` (optimized for manipulation, not storage density) doesn't pay.
- All three libraries provide String-like APIs (`push_str`, format macros, slicing), so migrating existing code is largely mechanical — but measure memory before adopting, since the win depends on your actual string-length distribution.

## References
- [mem-boxed-slice](mem-boxed-slice.md)
- [own-cow-conditional](own-cow-conditional.md)
- [mem-smallvec](mem-smallvec.md)
