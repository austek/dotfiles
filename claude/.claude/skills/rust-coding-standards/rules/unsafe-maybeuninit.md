---
title: Use MaybeUninit for Uninitialized Memory
impact: CRITICAL
impactDescription: Avoids undefined behavior from invalid bit patterns
tags: [unsafe, maybeuninit, undefined-behavior, memory]
---

# Use MaybeUninit for Uninitialized Memory [CRITICAL]

## Description
`mem::uninitialized()` was deprecated in Rust 1.39 and is immediate undefined behavior for any type with validity invariants — `bool` (only bit patterns `0`/`1` are valid), `&T` (must be non-null and aligned), `NonZeroU32`, `char`, and enums. Even `mem::zeroed()` is UB for references and `NonZero*` types, since zero is not a valid bit pattern for them. `MaybeUninit<T>` is the correct abstraction: it wraps possibly-uninitialized memory without ever claiming to hold a valid `T`, so the compiler cannot miscompile around an invariant that was never actually true. The standard library uses it pervasively — `Vec`'s spare capacity, array initialization, and FFI buffers all go through `MaybeUninit`.

## Bad Example
```rust
use std::mem;

// Instant UB: bool has validity invariants; uninitialized bits are not
// guaranteed to be 0 or 1. The optimizer may miscompile code that follows.
let b: bool = unsafe { mem::uninitialized() };

// Also UB for references — a zero reference is immediately invalid.
let r: &u32 = unsafe { mem::zeroed() };
```

## Good Example
```rust
use std::mem::MaybeUninit;

// Single value
let mut x = MaybeUninit::<u32>::uninit();
x.write(42);
// SAFETY: we just wrote a valid u32 via `write`, so the value is initialized.
let value: u32 = unsafe { x.assume_init() };

// Growing a Vec into its own spare capacity
fn fill_vec(v: &mut Vec<u8>, extra: usize) {
    v.reserve(extra);
    let spare = v.spare_capacity_mut(); // &mut [MaybeUninit<u8>]
    for slot in spare.iter_mut().take(extra) {
        slot.write(0u8);
    }
    // SAFETY: we initialized `extra` elements in the spare capacity above.
    unsafe { v.set_len(v.len() + extra) };
}
```

## Notes
- `assume_init()` is sound only after every byte is actually initialized — via `write`, a filled FFI buffer, or another provably complete path. Calling it on partially-initialized memory is undefined behavior even if you never read the uninitialized part.
- Build an array of uninitialized slots with `[const { MaybeUninit::uninit() }; N]`, which works for any `T` without requiring `Copy`; convert a fully-initialized `[MaybeUninit<T>; N]` to `[T; N]` via `MaybeUninit::<[T; N]>::from(arr).assume_init()`.
- `Vec::spare_capacity_mut()` returns `&mut [MaybeUninit<T>]` — the idiomatic way to write into a `Vec`'s reserved-but-unused capacity before advancing its length with `set_len`.
- `mem::zeroed()` is technically sound for types where an all-zero bit pattern is valid for every field (plain `u8`, `i32`, simple C structs) — but `MaybeUninit` remains the clearer choice even there, since it documents intent rather than relying on the reader to verify zero-validity by hand.
- `mem::uninitialized` has no safe migration path; every remaining usage should be replaced with `MaybeUninit`, not merely silenced.

## References
- [unsafe-safety-comment](unsafe-safety-comment.md)
- [mem-with-capacity](mem-with-capacity.md)
