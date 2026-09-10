---
title: Use AsRef<T> When You Only Need to Borrow
impact: MEDIUM
impactDescription: Accepts multiple input types with zero allocation overhead
tags: [api-design, asref, borrowing, generics]
---

# Use AsRef<T> When You Only Need to Borrow [MEDIUM]

## Description
`AsRef<T>` provides a cheap borrowed view of data without taking ownership or allocating. A function that accepts `impl AsRef<T>` can work uniformly with `&str`, `String`, and `Cow<str>` — or with `&Path`, `String`, and `PathBuf` — without forcing callers to convert to one exact type first. The rule of thumb: use `AsRef` when the function only needs to *read* the data, and `Into` when it needs to *own* or store the value going forward.

## Bad Example
```rust
// Forces callers to provide the exact type
fn read_file(path: &Path) { ... }

let p = PathBuf::from("/file");
read_file(&p);        // Works, but verbose
read_file("/file");   // Error: &str != &Path
```

## Good Example
```rust
// Accept anything that can be viewed as the target type
fn read_file(path: impl AsRef<Path>) -> io::Result<Vec<u8>> {
    std::fs::read(path.as_ref())
}

// All of these work directly:
read_file("/path/to/file");         // &str
read_file(Path::new("/path"));      // &Path
read_file(PathBuf::from("/path"));  // PathBuf
```

## Notes
- Decision table: a single, simple call site → plain `&T`; read-only access across several possible input types → `AsRef<T>`; the function needs to store or take ownership of the value → `Into<T>`; a `HashMap`/`HashSet` key lookup that must respect `Eq`/`Hash` consistency → `Borrow<T>` instead of `AsRef`.
- Implementing `AsRef<str>` and `AsRef<[u8]>` for a custom wrapper type (`Name(String)`) lets it flow into any function already written against those standard bounds, without that function knowing your type exists.
- `count_bytes(data: impl AsRef<[u8]>)` accepts `&str`, `&[u8]`, and `Vec<u8>` uniformly, calling `.as_ref()` once inside — this is strictly cheaper than an `Into<Vec<u8>>` bound, which would force an allocation for borrowed input.
- The standard library already implements `AsRef<str>`/`AsRef<[u8]>`/`AsRef<Path>` for `String`, `str`, `Vec<u8>`, `PathBuf`, and `OsStr` — check whether your desired conversion already exists before writing a custom bound.
- `AsRef<T> + ?Sized` bounds (`fn process<T: AsRef<U> + ?Sized, U: ?Sized>(value: &T)`) extend the pattern to unsized types like `str` and `[T]`, letting callers pass either an owned value or an existing reference.

## References
- [api-impl-into](api-impl-into.md)
- [own-slice-over-vec](own-slice-over-vec.md)
- [own-borrow-over-clone](own-borrow-over-clone.md)
