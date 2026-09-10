---
title: Use Arc for Thread-Safe Shared Ownership
impact: HIGH
impactDescription: Safe concurrent sharing without data races
tags: [ownership, concurrency, arc, thread-safety]
---

# Use Arc for Thread-Safe Shared Ownership [HIGH]

## Description
`Arc<T>` (Atomically Reference Counted) provides shared ownership across threads. Unlike `Rc<T>`, its reference count is updated atomically, so cloning and dropping an `Arc` handle is safe from multiple threads at once. Reach for it whenever data must outlive a single thread and multiple owners need read access to it; pair it with `Mutex`/`RwLock` when the shared data must also be mutated.

## Bad Example
```rust
use std::rc::Rc;
use std::thread;

let data = Rc::new(vec![1, 2, 3]);
let data_clone = Rc::clone(&data);

// ERROR: Rc cannot be sent between threads safely (Rc is !Send)
thread::spawn(move || {
    println!("{:?}", data_clone);
});
```

## Good Example
```rust
use std::sync::{Arc, Mutex};
use std::thread;

// Read-only sharing
let data = Arc::new(vec![1, 2, 3]);
let data_clone = Arc::clone(&data);
thread::spawn(move || {
    println!("{:?}", data_clone); // Safe!
});
println!("{:?}", data); // Original still accessible

// Mutable shared state: Arc<Mutex<T>>
let counter = Arc::new(Mutex::new(0));
let mut handles = vec![];
for _ in 0..10 {
    let counter = Arc::clone(&counter);
    handles.push(thread::spawn(move || {
        let mut num = counter.lock().unwrap();
        *num += 1;
    }));
}
for handle in handles {
    handle.join().unwrap();
}
println!("Result: {}", *counter.lock().unwrap());
```

## Notes
- Decision rule: no shared ownership → use owned values or references; shared but single-threaded → `Rc<T>`; shared across threads → `Arc<T>`; shared and mutable across threads → `Arc<Mutex<T>>` or `Arc<RwLock<T>>`.
- `Arc::clone` is cheap — it only increments an atomic counter, no data is copied — but the atomic operation still has overhead versus `Rc::clone`, so prefer `Rc` in single-threaded code.
- Clone the `Arc` once outside a hot loop and pass a reference into the loop body instead of cloning on every iteration.
- A common pattern is `Arc<RwLock<HashMap<K, V>>>` for a shared, read-heavy cache accessed from multiple worker threads.

## References
- [own-rc-single-thread](own-rc-single-thread.md)
- [own-mutex-interior](own-mutex-interior.md)
- [own-rwlock-readers](own-rwlock-readers.md)
- [async-clone-before-await](async-clone-before-await.md)
