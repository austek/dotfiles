---
title: Clone Arc/Rc Data Before Await Points
impact: HIGH
impactDescription: Avoids Send-bound failures and borrow-lifetime complications
tags: [async, arc, send, borrowing]
---

# Clone Arc/Rc Data Before Await Points [HIGH]

## Description
A reference held across an `.await` point extends into the generated future's captured state, since the future must be able to resume from that exact point later. If the reference is to `!Send` data (like the contents behind an `Rc`), the resulting future becomes `!Send` too, which fails to compile the moment you try to `tokio::spawn` it on a multi-threaded runtime. Cloning the `Arc`/`Rc` (or just the specific field you need) before the `.await` sidesteps the problem entirely: the future then holds owned data, is `Send` when its contents are `Send`, and has no borrow-lifetime tangled through the suspension point.

## Bad Example
```rust
use std::sync::Arc;

async fn process(data: Arc<Data>) {
    // Borrow extends across await — future is not Send
    let slice = &data.items[..];
    expensive_async_operation().await;  // Await with an active borrow
    use_slice(slice);
}

// Error: future cannot be sent between threads safely
tokio::spawn(process(data));
```

## Good Example
```rust
use std::sync::Arc;

async fn process(data: Arc<Data>) {
    // Clone what's needed before the await — owned data crosses the suspension
    let items = data.items.clone();
    expensive_async_operation().await;
    use_items(&items);
}

// Or clone the Arc itself when the whole thing is needed afterward
async fn share_data(data: Arc<Data>) {
    let data = data.clone();  // Cheap: another handle to the same allocation
    some_async_work().await;
    process(&data);
}
```

## Notes
- Clone only what you actually need across the await, not the whole structure — `data.small_field.clone()` before an await beats `(*data).clone()` cloning the entire `LargeData` just to use one field afterward.
- `Rc<T>` is `!Send`; holding one across an await on code that might run on a multi-threaded runtime is the single most common source of "future cannot be sent between threads safely" errors — switch to `Arc<T>` the moment async code needs to share the value.
- Scoping a borrow to end before the await (`let computed = { let slice = &data.items[..]; compute(slice) };`) achieves the same effect as cloning without the allocation, when the borrow's result can be computed synchronously and only that result is needed after the await.
- A `MutexGuard` held across an `.await` is a specific, especially dangerous instance of this same pattern — see the companion rule on never holding locks across await for why it deserves separate attention.
- `Arc::clone(&data)` inside a loop before each `tokio::spawn` is the standard idiom for giving each spawned task its own handle to shared state — clone once per task, immediately before the `move` closure that captures it.

## References
- [async-no-lock-await](async-no-lock-await.md)
- [own-arc-shared](own-arc-shared.md)
- [async-spawn-blocking](async-spawn-blocking.md)
