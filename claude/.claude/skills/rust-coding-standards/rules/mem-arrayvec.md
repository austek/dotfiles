---
title: Use ArrayVec for Fixed-Capacity Stack Collections
impact: MEDIUM
impactDescription: Guaranteed zero heap allocation for bounded collections
tags: [memory, allocation, arrayvec, no-heap]
---

# Use ArrayVec for Fixed-Capacity Stack Collections [MEDIUM]

## Description
`ArrayVec<T, N>` from the `arrayvec` crate offers a `Vec`-like API backed by inline stack storage with a compile-time maximum capacity. Unlike `SmallVec`, which spills to the heap once it outgrows its inline buffer, `ArrayVec` never allocates — pushing past capacity returns an error (`try_push`) or panics (`push`). Reach for it when a hard upper bound is part of the domain (a fixed number of RGBA channels, a bounded parser lookahead) and heap allocation must be provably absent, such as embedded or `no_std` contexts.

## Bad Example
```rust
// Vec always heap-allocates, even though the count is capped at 8
fn parse_options(input: &str) -> Vec<Option> {
    let mut options = Vec::new();  // Heap allocation
    for part in input.split(',').take(8) {
        options.push(parse_option(part));
    }
    options
}

// SmallVec can still heap-allocate if pushed beyond its inline capacity —
// unexpected in a context that must never allocate
use smallvec::SmallVec;
fn get_flags() -> SmallVec<[Flag; 4]> {
    todo!()
}
```

## Good Example
```rust
use arrayvec::ArrayVec;

// Guaranteed no heap allocation
fn parse_options(input: &str) -> ArrayVec<Option<u32>, 8> {
    let mut options = ArrayVec::new();
    for part in input.split(',') {
        if options.try_push(parse_option(part)).is_err() {
            break;  // Capacity reached, stop rather than allocate
        }
    }
    options
}

// For embedded/no_std contexts
fn collect_readings() -> ArrayVec<SensorReading, 16> {
    let mut readings = ArrayVec::new();
    for sensor in SENSORS.iter() {
        readings.push(sensor.read());  // Panics past 16 — capacity is a domain fact
    }
    readings
}
```

## Notes
- Decision rule: `Vec<T>` for unbounded or unknown size; `SmallVec<[T; N]>` when usually small but occasionally large; `ArrayVec<T, N>` when there is a hard limit and heap allocation is disallowed.
- `try_push` returns `Err` with the rejected element attached, so callers can recover it instead of losing data to a panic.
- `ArrayString<N>` is the string equivalent — a stack-allocated, fixed-capacity string, useful for short formatted codes built with `write!`.
- Avoid `ArrayVec` when the capacity is large (megabyte-sized inline storage blows the stack) or when the size genuinely varies without a natural bound — use `SmallVec` or `Vec` there instead.
- Collecting into an `ArrayVec` from an iterator still needs an explicit `.take(N)` — the type alone does not truncate an oversized iterator for you.

## References
- [mem-smallvec](mem-smallvec.md)
- [mem-with-capacity](mem-with-capacity.md)
- [arrayvec crate](https://docs.rs/arrayvec)
