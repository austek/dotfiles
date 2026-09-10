---
title: Box Large Enum Variants to Shrink the Whole Enum
impact: MEDIUM
impactDescription: Every instance shrinks to the size of the largest remaining variant
tags: [memory, enum, box, layout]
---

# Box Large Enum Variants to Shrink the Whole Enum [MEDIUM]

## Description
An enum's size is the size of its largest variant plus a discriminant. If one variant embeds a large struct or array while the rest are small, every instance of the enum — including the small ones — pays for the largest variant's footprint, because Rust must reserve enough space for whichever variant is active. Boxing the oversized variant moves its data to the heap, leaving only a pointer inline, so the enum shrinks to the size of its next-largest variant. `clippy::large_enum_variant` flags this automatically.

## Bad Example
```rust
enum Message {
    Quit,                       // 0 bytes of data
    Move { x: i32, y: i32 },    // 8 bytes
    Text(String),                // 24 bytes
    Image {
        data: [u8; 1024],       // 1024 bytes — forces the whole enum to ~1032 bytes
        width: u32,
        height: u32,
    },
}

// Every Message is ~1032 bytes, even Quit and Move
let messages: Vec<Message> = vec![
    Message::Quit,                  // Wastes ~1032 bytes
    Message::Move { x: 0, y: 0 },   // Wastes ~1024 bytes
];
```

## Good Example
```rust
struct ImageData {
    data: [u8; 1024],
    width: u32,
    height: u32,
}

enum Message {
    Quit,
    Move { x: i32, y: i32 },
    Text(String),
    Image(Box<ImageData>),  // Now just 8 bytes (a pointer)
}

// Message is now ~32 bytes (the String variant is now the largest)
let messages: Vec<Message> = vec![
    Message::Quit,                  // ~32 bytes
    Message::Move { x: 0, y: 0 },   // ~32 bytes
];
```

## Notes
- `clippy::large_enum_variant = "warn"` catches this automatically — enable it in `[lints.clippy]` rather than relying on manual review.
- Recursive types (`enum List { Cons(i32, List), Nil }`) are not just a size optimization but a compiler requirement — an unboxed recursive variant has infinite size and will not compile.
- Rough guideline: don't box variants under ~64 bytes when the rest are similarly sized; box variants over ~128–256 bytes when others are much smaller — but measure the actual size with `size_of` rather than guessing.
- Pattern matching on a boxed variant auto-derefs through the `Box` when matching by reference (`&Event::Large(data) => ...`), so call sites usually need no changes beyond the field's declared type.
- Combine with `mem-assert-type-size` on hot enums to catch future variant growth automatically.

## References
- [mem-assert-type-size](mem-assert-type-size.md)
- [mem-smallvec](mem-smallvec.md)
