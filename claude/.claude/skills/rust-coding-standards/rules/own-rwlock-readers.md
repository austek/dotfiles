---
title: Use RwLock When Reads Significantly Outnumber Writes
impact: MEDIUM
impactDescription: Concurrent readers instead of fully serialized access
tags: [ownership, concurrency, rwlock, performance]
---

# Use RwLock When Reads Significantly Outnumber Writes [MEDIUM]

## Description
`Mutex<T>` allows only one thread to access data at a time, even for reads that don't conflict with each other. `RwLock<T>` allows either multiple concurrent readers or one exclusive writer. For read-heavy workloads — configuration that's read constantly but updated rarely, caches, shared lookup tables — this removes unnecessary serialization between readers and meaningfully improves throughput.

## Bad Example
```rust
use std::sync::{Arc, Mutex};

// Configuration rarely changes but is read constantly
let config = Arc::new(Mutex::new(Config::load()));

fn get_setting(config: &Mutex<Config>, key: &str) -> String {
    let guard = config.lock().unwrap(); // Every read blocks other reads too
    guard.get(key).to_string()
}
// 100 threads reading = serialized, one at a time
```

## Good Example
```rust
use std::sync::{Arc, RwLock};

let config = Arc::new(RwLock::new(Config::load()));

fn get_setting(config: &RwLock<Config>, key: &str) -> String {
    let guard = config.read().unwrap(); // Multiple threads can hold a read lock
    guard.get(key).to_string()
}

fn update_setting(config: &RwLock<Config>, key: &str, value: &str) {
    let mut guard = config.write().unwrap(); // Exclusive access for writes
    guard.set(key, value);
}
// 100 threads reading = parallel execution
```

## Notes
- `RwLock` has bookkeeping overhead for tracking readers, so it can lose to `Mutex` when writes are frequent (over roughly 20% of operations) or the lock is held only very briefly.
- The standard-library `RwLock` may starve writers under continuous read load; `parking_lot::RwLock` is writer-fair by default and also offers an `upgradable_read()` lock for check-then-write patterns without a full write lock upfront.
- Common pattern: `RwLock<Option<T>>` as a cache — fast-path a `read()` to check if a cached value exists, fall back to `write()` only to populate it.

## References
- [own-mutex-interior](own-mutex-interior.md)
- [own-arc-shared](own-arc-shared.md)
