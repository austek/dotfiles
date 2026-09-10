---
title: Use Mutex for Interior Mutability Across Threads
impact: HIGH
impactDescription: Data-race-free shared mutable state, enforced at compile time
tags: [ownership, concurrency, mutex, interior-mutability]
---

# Use Mutex for Interior Mutability Across Threads [HIGH]

## Description
When multiple threads need to mutate shared state, `Mutex<T>` provides safe interior mutability with OS-level locking: only one thread can access the guarded data at a time. Unlike `RefCell<T>`, `Mutex<T>` is `Send + Sync`, so the compiler will reject any attempt to share a `RefCell` across threads while accepting a `Mutex` — the type system enforces the correct choice.

## Bad Example
```rust
use std::cell::RefCell;
use std::sync::Arc;

// RefCell is !Sync - this won't compile
let shared = Arc::new(RefCell::new(vec![]));

// ERROR: RefCell cannot be shared between threads safely
std::thread::spawn({
    let shared = shared.clone();
    move || shared.borrow_mut().push(1)
});
```

## Good Example
```rust
use std::sync::{Arc, Mutex};

let shared = Arc::new(Mutex::new(vec![]));

let handles: Vec<_> = (0..10).map(|i| {
    let shared = shared.clone();
    std::thread::spawn(move || {
        let mut data = shared.lock().unwrap();
        data.push(i);
    })
}).collect();

for handle in handles {
    handle.join().unwrap();
}
println!("{:?}", shared.lock().unwrap()); // All values present
```

## Notes
- If a thread panics while holding the lock, the `Mutex` becomes "poisoned"; `lock()` then returns `Err`. Recover with `poisoned.into_inner()` (or `.unwrap_or_else(|e| e.into_inner())`) if the data is still usable, rather than propagating the panic further.
- `parking_lot::Mutex` is a common drop-in replacement: it never poisons (the guard is returned directly, no `Result` to unwrap), is smaller (1 byte vs 40+), and performs better under contention.
- Decision guide: single-threaded interior mutability → `RefCell<T>`; shared mutable state across threads → `Mutex<T>`; many readers, few writers → `RwLock<T>`.

## References
- [own-rwlock-readers](own-rwlock-readers.md)
- [own-refcell-interior](own-refcell-interior.md)
- [own-arc-shared](own-arc-shared.md)
