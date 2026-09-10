---
title: Know and Control Drop Order
impact: HIGH
impactDescription: Prevents lock-before-commit and resource-teardown bugs
tags: [memory, drop, raii, ordering]
---

# Know and Control Drop Order [HIGH]

## Description
Drop order is observable, not an implementation detail. RAII guards — mutex locks, file handles, database transactions, tracing span guards — do meaningful work in `Drop`, and dropping them in the wrong order causes silent bugs: releasing a lock before a transaction that depends on it commits, or closing a connection before its transaction finishes. The rules are fixed: struct fields drop in declaration order (top to bottom); local variables drop in reverse declaration order (last-in, first-out). Getting this right means treating field and local ordering as part of a type's contract, not an afterthought.

## Bad Example
```rust
struct Transaction; // pretend this commits on drop
impl Drop for Transaction {
    fn drop(&mut self) {
        println!("transaction committed");
    }
}

struct DatabaseSession {
    // BUG: `guard` is declared first, so it drops FIRST — releasing the
    // mutex while `transaction` is still in-flight below it.
    guard: MutexGuard<'static, ()>,
    transaction: Transaction,
}
```

## Good Example
```rust
struct Transaction; // commits on drop
impl Drop for Transaction {
    fn drop(&mut self) {
        println!("transaction committed");
    }
}

struct DatabaseSession {
    // CORRECT: transaction drops first (commit happens), then guard drops
    // (lock released) — declaration order is the drop-order contract.
    transaction: Transaction,
    guard: MutexGuard<'static, ()>,
}

// For locals, when the natural reverse-declaration order is wrong,
// drop explicitly:
fn process(conn: Connection, txn: Transaction, guard: LockGuard) {
    do_work(&txn);
    drop(guard);   // Release lock explicitly before txn commits
    txn.commit();  // Runs before conn closes
} // conn drops here
```

## Notes
- Tuple and array elements drop in index order (0, 1, 2, ...); function arguments drop in reverse parameter-list order — the same reverse rule as locals.
- Add a short comment at the declaration site when ordering is load-bearing: `// NOTE: drop order matters — transaction before connection` — the field order alone doesn't explain *why* to a future editor who reorders fields for style reasons.
- `std::mem::ManuallyDrop<T>` opts a field out of automatic drop entirely, needed when moving a value out of a struct inside its own `Drop::drop` (only `&mut self` is available there).
- `std::mem::forget` doesn't reorder anything — it leaks the value, running no destructor at all; reserve it for FFI ownership hand-off, never as a substitute for correct ordering.
- Prefer explicit `drop(x)` calls over relying on scope-exit order whenever the correct sequence isn't obvious from the code as written.

## References
- [own-mutex-interior](own-mutex-interior.md)
- [mem-take-replace](mem-take-replace.md)
