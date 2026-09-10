---
title: Write #[unsafe(no_mangle)] Instead of Bare Attribute Forms
impact: HIGH
impactDescription: Surfaces linker symbol-collision risk that was previously invisible
tags: [unsafe, ffi, no-mangle, rust-2024]
---

# Write #[unsafe(no_mangle)] Instead of Bare Attribute Forms [HIGH]

## Description
`#[no_mangle]`, `#[export_name]`, and `#[link_section]` were reclassified as unsafe in Rust 2024 because they can cause undefined behavior with no `unsafe` block anywhere at the call site. If two items in the same binary export the same symbol name, the linker silently keeps one and discards the other — the "winning" symbol may have a completely different type or signature than callers expect, producing type-level UB with no compiler or linker diagnostic. Requiring `#[unsafe(...)]` makes that footgun visible in the source instead of hiding in link-time behavior.

## Bad Example
```rust
// Rust 2021 — bare attributes accepted, no warning about the linker-UB risk
#[no_mangle]
pub extern "C" fn init() {
    // ...
}

#[export_name = "plugin_entry"]
pub fn plugin_main() {
    // ...
}
```

## Good Example
```rust
// Rust 2024 — the unsafe(...) wrapper makes the risk explicit
#[unsafe(no_mangle)]
pub extern "C" fn init() {
    // ...
}

#[unsafe(export_name = "plugin_entry")]
pub fn plugin_main() {
    // ...
}

#[unsafe(link_section = ".init_array")]
static INIT: extern "C" fn() = init;
```

## Notes
- The `unsafe(...)` wrapper does not require an `unsafe {}` block at any call site — it marks the *attribute itself* as load-bearing for safety, documenting that the author accepted responsibility for symbol uniqueness and ABI correctness.
- Symbol collisions are especially dangerous in plugin architectures, `cdylib` crates, embedded firmware with custom linker scripts, and any codebase linking multiple Rust crates into one binary.
- `cargo fix --edition` rewrites bare attribute forms to `#[unsafe(...)]` automatically when migrating to the 2024 edition; still manually confirm each exported symbol name is unique across the binary afterward.
- These attributes interact with `unsafe extern` blocks: symbols you export and symbols you import from C both follow the same 2024-edition explicit-unsafe rules.
- The bare forms are a hard compile error under the Rust 2024 edition; they still compile under earlier editions but emit a deprecation warning under `--warn future-incompatible`.

## References
- [unsafe-extern-block](unsafe-extern-block.md)
