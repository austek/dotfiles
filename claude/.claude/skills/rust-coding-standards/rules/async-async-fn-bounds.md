---
title: Use AsyncFn Bounds Instead of F: Fn() -> Fut
impact: MEDIUM
impactDescription: Correctly accepts async closures that borrow their environment
tags: [async, closures, generics, rust-2024]
---

# Use AsyncFn Bounds Instead of F: Fn() -> Fut [MEDIUM]

## Description
`AsyncFn`, `AsyncFnMut`, and `AsyncFnOnce` stabilized in Rust 1.85 and express a higher-order async function bound in a single, readable constraint instead of the older two-generic workaround (`F: Fn() -> Fut, Fut: Future<Output = T>`). The old pattern has a real correctness gap, not just a verbosity one: it cannot accept `async ||` closures that borrow from their environment, because nothing links the returned future's lifetime back to the call. `AsyncFn` fixes this structurally, so higher-order functions that accept retry logic, callbacks, or middleware can take genuine async closures, not just top-level `async fn` items.

## Bad Example
```rust
use std::future::Future;

// Two-generic pattern: verbose, and cannot accept async closures
// that borrow from their environment across the call
async fn retry<F, Fut, T, E>(times: usize, f: F) -> Result<T, E>
where
    F: Fn() -> Fut,
    Fut: Future<Output = Result<T, E>>,
{
    for _ in 0..times {
        if let Ok(v) = f().await {
            return Ok(v);
        }
    }
    f().await
}
```

## Good Example
```rust
// AsyncFn bound: concise, correct lifetime semantics, accepts async closures
async fn retry<F, T, E>(times: usize, f: F) -> Result<T, E>
where
    F: AsyncFn() -> Result<T, E>,
{
    for _ in 0..times {
        if let Ok(v) = f().await {
            return Ok(v);
        }
    }
    f().await
}

async fn example() {
    // Async closure that borrows a local across calls — impossible
    // with the old F: Fn() -> Fut pattern
    let prefix = "prefix".to_owned();
    let _ = retry(3, async || {
        Ok::<_, std::io::Error>(format!("{prefix}-data"))
    }).await;
}
```

## Notes
- The three variants mirror `Fn`/`FnMut`/`FnOnce` exactly: `AsyncFn` takes `&self` (callable repeatedly, no mutation), `AsyncFnMut` takes `&mut self` (repeatedly, may mutate captured state), `AsyncFnOnce` takes `self` (exactly once, may consume captured state) — apply the same "prefer the least restrictive bound" rule as with the synchronous traits.
- Plain top-level `async fn` items automatically implement `AsyncFn` when their signature matches, so migrating a bound from `F: Fn() -> Fut` to `F: AsyncFn()` doesn't break callers passing ordinary async functions.
- The compiler still infers `Send`-ness of the returned future from the closure body — if the future must be `Send` (spawning on a multi-threaded Tokio runtime), add `+ Send` to the bound explicitly rather than assuming it.
- In the 2024 edition, `AsyncFn` traits are in scope automatically; in earlier editions, `use std::ops::AsyncFn;` may be required.

## References
- [async-fn-in-trait](async-fn-in-trait.md)
- [async-tokio-runtime](async-tokio-runtime.md)
