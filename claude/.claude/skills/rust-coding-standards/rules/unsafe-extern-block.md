---
title: Wrap extern Blocks in unsafe extern With Per-Item Safety
impact: HIGH
impactDescription: Makes FFI safety obligations explicit and auditable
tags: [unsafe, ffi, extern, rust-2024]
---

# Wrap extern Blocks in unsafe extern With Per-Item Safety [HIGH]

## Description
Before Rust 2024, every function declared in an `extern "C" { }` block was implicitly unsafe to call, but the block itself carried no `unsafe` marker — nothing forced the author to acknowledge that the FFI contract (correct types, valid pointers, no aliasing violations) was entirely their responsibility to verify. Rust 2024 requires `unsafe extern { }`, an explicit assertion that the declarations accurately describe the external ABI, and lets each item be marked `safe` (callable without an `unsafe` block) or `unsafe` (the default, caller must wrap the call). This makes FFI boundaries auditable at a glance instead of implicit.

## Bad Example
```rust
// Rust 2021 style — compiles, but forbidden under the 2024 edition
extern "C" {
    fn strlen(s: *const std::ffi::c_char) -> usize;
    fn memcpy(dst: *mut u8, src: *const u8, n: usize) -> *mut u8;
    static errno: std::ffi::c_int;
}
```

## Good Example
```rust
// Rust 2024 style
unsafe extern "C" {
    // Genuinely unsafe: caller must pass a null-terminated pointer.
    pub unsafe fn strlen(s: *const std::ffi::c_char) -> usize;

    // Unsafe: caller must ensure non-overlapping, valid regions.
    pub unsafe fn memcpy(dst: *mut u8, src: *const u8, n: usize) -> *mut u8;

    // Always safe to call (hypothetical pure query).
    pub safe fn rust_version_major() -> u32;

    // Statics are unsafe unless the caller can guarantee no data races.
    pub unsafe static errno: std::ffi::c_int;
}

fn copy_bytes(dst: *mut u8, src: *const u8, n: usize) {
    // SAFETY: dst and src are non-overlapping, both valid for n bytes.
    unsafe { memcpy(dst, src, n) };
}

fn show_version() {
    println!("major: {}", rust_version_major());  // No unsafe block needed
}
```

## Notes
- The `unsafe` on the block means "these declarations faithfully describe the external ABI" — it does not, by itself, make calls to the declared items safe.
- Marking an item `safe` is a promise: if the item is actually unsafe to call and you mark it `safe`, that is itself unsound, and the compiler cannot catch a wrong annotation.
- `cargo fix --edition` performs the mechanical migration automatically (wrapping blocks, marking items `unsafe`); review each item afterward to decide whether `safe` is actually warranted.
- Updated `bindgen` (0.70+) and `cbindgen` emit `unsafe extern` blocks for Rust 2024 output — update your code generator if you use one, rather than hand-patching generated code.
- The same 2024-edition rules apply to `#[unsafe(no_mangle)]` and related export attributes on the exporting side of an FFI boundary.

## References
- [unsafe-no-mangle-unsafe](unsafe-no-mangle-unsafe.md)
- [unsafe-safety-comment](unsafe-safety-comment.md)
