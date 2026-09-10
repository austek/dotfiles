---
title: Use RefCell for Interior Mutability in Single-Threaded Code
impact: MEDIUM
impactDescription: Enables mutation through &self where the borrow checker is too strict
tags: [ownership, refcell, interior-mutability, single-threaded]
---

# Use RefCell for Interior Mutability in Single-Threaded Code [MEDIUM]

## Description
The borrow checker enforces aliasing rules at compile time, but some patterns — caches, lazy initialization, observer callbacks — need to mutate data through a shared reference. `RefCell<T>` moves borrow checking to runtime, allowing `&self` methods to mutate the contents via `borrow_mut()`. This is essential when the compile-time borrow checker is too conservative for a pattern that is actually safe, at the cost of a possible runtime panic if the rules are violated.

## Bad Example
```rust
struct Cache {
    // Requires &mut self to update, which breaks shared-reference patterns
    data: HashMap<String, String>,
}

impl Cache {
    fn get_or_compute(&mut self, key: &str) -> &str {
        // Caller needs &mut Cache, so the cache can't be shared while in use
        if !self.data.contains_key(key) {
            self.data.insert(key.to_string(), expensive_compute(key));
        }
        &self.data[key]
    }
}
```

## Good Example
```rust
use std::cell::RefCell;
use std::collections::HashMap;

struct Cache {
    data: RefCell<HashMap<String, String>>,
}

impl Cache {
    fn get_or_compute(&self, key: &str) -> String {
        // Can mutate through &self
        let mut data = self.data.borrow_mut();
        if !data.contains_key(key) {
            data.insert(key.to_string(), expensive_compute(key));
        }
        data[key].clone()
    }
}

// Multiple shared references can coexist
let cache = Cache::new();
let ref1 = &cache;
let ref2 = &cache;
ref1.get_or_compute("key1");
ref2.get_or_compute("key2");
```

## Notes
- `RefCell` panics if borrowing rules are violated at runtime — e.g. calling `borrow_mut()` while a `borrow()` is still live. Use `try_borrow()`/`try_borrow_mut()` when a violation is a recoverable condition rather than a bug.
- For simple `Copy` values, `Cell<T>` is lighter than `RefCell<T>`: no runtime borrow flags, no panics, just `get()`/`set()`/`replace()`.
- Combining `Rc<RefCell<T>>` is the standard pattern for shared mutable state in single-threaded code, such as passing shared, mutable application state into multiple closures.

## References
- [own-rc-single-thread](own-rc-single-thread.md)
- [own-mutex-interior](own-mutex-interior.md)
