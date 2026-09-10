---
title: Use Appropriately-Sized Integers to Reduce Memory Footprint
impact: MEDIUM
impactDescription: Reduces per-instance size and improves cache utilization
tags: [memory, integers, layout, cache]
---

# Use Appropriately-Sized Integers to Reduce Memory Footprint [MEDIUM]

## Description
Reaching for `i64`/`u64` by default when a value's domain fits in `u8` or `u16` wastes bytes that compound across arrays, vectors, and structs with many instances — a color channel (0–255) needs a `u8`, not a `u64`. Choosing the smallest integer type the domain actually requires shrinks memory usage and improves cache line utilization, since more instances fit per cache line. Field ordering matters too: placing larger fields before smaller ones reduces padding from alignment requirements.

## Bad Example
```rust
struct Pixel {
    r: u64,  // Color channels need 0-255 = 8 bits
    g: u64,  // Using 64 bits is 8x more than needed
    b: u64,
    a: u64,
}
// Size: 32 bytes per pixel

struct HttpStatus {
    code: i32,      // HTTP codes 100-599 fit in 10 bits
    version: i32,   // HTTP 1.0/1.1/2/3 fits in 2 bits
}
// Size: 8 bytes per status
```

## Good Example
```rust
struct Pixel {
    r: u8,
    g: u8,
    b: u8,
    a: u8,
}
// Size: 4 bytes per pixel — 8x smaller

struct HttpStatus {
    code: u16,   // 100-599 fits in u16
    version: u8, // 1, 2, 3 fits in u8
}
// Size: 3 bytes (+1 padding = 4 bytes)
```

## Notes
- Field ordering affects padding independent of type choice: placing an 8-byte field before two 1-byte fields (`u64, u8, u8`) packs into 16 bytes, while `u8, u64, u8` pads to 24 — put larger-aligned fields first.
- Widening conversions (`u8` into `u32` via `.into()`) always succeed; narrowing conversions can overflow, so use `.try_into()` or `TryFrom` and handle the `Err` case rather than an `as` cast that silently truncates.
- `bitflags!` packs many boolean flags into a single integer (8 flags in 1 byte) instead of 8 separate `bool` fields, each of which costs at least a byte plus potential padding.
- `Option<NonZeroU64>` is 8 bytes because Rust uses the value `0` as the niche for `None` — `Option<u64>` is 16 bytes because no such niche exists. Prefer `NonZero*` types for IDs and handles that are never legitimately zero.
- Don't over-optimize a struct with only a handful of instances (application config, a one-off request struct) — the payoff is in types instantiated at scale.

## References
- [mem-box-large-variant](mem-box-large-variant.md)
- [mem-assert-type-size](mem-assert-type-size.md)
