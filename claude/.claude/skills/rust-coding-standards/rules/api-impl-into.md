---
title: Accept impl Into<T> for Flexible APIs
impact: MEDIUM
impactDescription: Removes explicit .into() calls at every call site
tags: [api-design, into, ergonomics, generics]
---

# Accept impl Into<T> for Flexible APIs [MEDIUM]

## Description
A function that requires the exact target type forces every caller to convert explicitly before the call, even when the conversion is trivial and unambiguous. Accepting `impl Into<T>` instead lets callers pass the target type directly or anything that converts to it, with the conversion happening once, inside the function. This is purely a call-site ergonomics choice — implement `From<T>` for the actual conversion logic (see `api-from-not-into`), and accept `impl Into<T>` at API boundaries that should feel natural to call with a string literal, an owned value, or anything in between.

## Bad Example
```rust
// Requires the exact type — forces callers to convert explicitly
fn set_name(name: String) { ... }

set_name(String::from("Alice"));
set_name("Alice".to_string());  // Verbose
```

## Good Example
```rust
// Accept anything that converts to the target type
fn set_name(name: impl Into<String>) {
    let name = name.into();  // Convert once, inside
}

// Callers are ergonomic
set_name("Alice");                 // &str
set_name(String::from("Alice"));   // String
set_name(format!("User-{}", id));  // String from format!
```

## Notes
- Implement `From<T>` for the underlying conversion, never `Into<T>` directly — the blanket impl in std gives you `Into` for free once `From` exists (see `api-from-not-into`).
- Choose `AsRef<T>` instead when the function only needs to *read* the value (no allocation, no ownership transfer); choose `Into<T>` when the function needs to *store or own* the converted value.
- Avoid `impl Into<T>` on hot paths called extremely frequently — the trait-dispatch and potential-conversion overhead, while usually negligible, is worth measuring if the function sits in a tight loop; taking `T` directly avoids the question entirely.
- `impl Into<T>` doesn't work as a struct field type or in other positions where the concrete type must be named (`Vec<impl Into<Node>>` is not valid) — it is a parameter-position tool only.
- Builder methods commonly pair `impl Into<String>`/`impl Into<PathBuf>` parameters with a consuming `mut self -> Self` signature, so `Config::new("myapp").path("/etc/myapp")` reads naturally without any `.into()` visible at the call site.

## References
- [api-impl-asref](api-impl-asref.md)
- [api-from-not-into](api-from-not-into.md)
- [err-from-impl](err-from-impl.md)
