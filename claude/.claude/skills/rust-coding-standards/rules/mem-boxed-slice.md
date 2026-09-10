---
title: Use Box<[T]> for Fixed-Size Heap Data
impact: LOW
impactDescription: Saves 8 bytes per instance versus Vec<T> on 64-bit
tags: [memory, box, slice, layout]
---

# Use Box<[T]> for Fixed-Size Heap Data [LOW]

## Description
`Vec<T>` carries three words — pointer, length, and capacity — because it supports growth. Once a collection is built and will never grow again, that capacity field is dead weight: `Box<[T]>` is a fat pointer of just pointer and length, two words instead of three. Converting with `.into_boxed_slice()` also communicates intent to readers: this data is finished and fixed-size, not a growable buffer someone might `.push()` into later. Across large numbers of instances (cache entries, parsed document sections), the saved 8 bytes per instance adds up.

## Bad Example
```rust
struct Document {
    // Vec signals "might grow", but nothing ever pushes after construction
    paragraphs: Vec<Paragraph>,  // 24 bytes: ptr + len + capacity
}

fn load_document(data: &[u8]) -> Document {
    let paragraphs: Vec<Paragraph> = parse_paragraphs(data);
    // paragraphs has capacity >= len; the extra capacity field is wasted
    Document { paragraphs }
}
```

## Good Example
```rust
struct Document {
    // Box<[T]> signals "fixed size" — clear intent, smaller footprint
    paragraphs: Box<[Paragraph]>,  // 16 bytes: ptr + len (fat pointer)
}

fn load_document(data: &[u8]) -> Document {
    let paragraphs: Vec<Paragraph> = parse_paragraphs(data);
    Document {
        paragraphs: paragraphs.into_boxed_slice(),  // Shrinks and converts
    }
}
```

## Notes
- `size_of::<Vec<u8>>()` is 24 bytes; `size_of::<Box<[u8]>>()` is 16 bytes — an 8-byte saving per instance, or roughly 8 MB across a million instances.
- Call `.shrink_to_fit()` on the `Vec` before `.into_boxed_slice()` if it may still have excess capacity from `with_capacity` or repeated pushes, otherwise the boxed slice inherits that wasted allocation.
- `Box<str>` is the string equivalent of `Box<[T]>` — 16 bytes versus `String`'s 24 — for immutable text that will never be appended to again.
- Converting back with `.into_vec()` (or `.into_string()` for `Box<str>`) is cheap and lets you regain growability later if requirements change.
- Prefer `[T; N]` over `Box<[T]>` when the size is known at compile time and small enough to live on the stack; reach for `&[T]` at call sites that only need to borrow, not own, the data.

## References
- [mem-with-capacity](mem-with-capacity.md)
- [own-slice-over-vec](own-slice-over-vec.md)
- [mem-compact-string](mem-compact-string.md)
