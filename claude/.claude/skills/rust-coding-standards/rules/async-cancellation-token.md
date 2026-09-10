---
title: Use CancellationToken for Graceful Shutdown
impact: HIGH
impactDescription: Cooperative cancellation instead of an abandoned, still-running task
tags: [async, cancellation, shutdown, tokio]
---

# Use CancellationToken for Graceful Shutdown [HIGH]

## Description
Dropping a `JoinHandle` does not cancel the task it was tracking — it only detaches the handle, leaving the task running to completion (or forever, for a loop) in the background. A boolean flag checked in a loop condition is async-unaware: if the task is currently suspended inside an `.await`, flipping the flag does nothing until that await resolves on its own. `tokio_util::sync::CancellationToken` is the correct cooperative primitive — it exposes an async `cancelled()` future that a task can race against its normal work in `select!`, waking it immediately when cancellation is requested rather than waiting for the current operation to finish.

## Bad Example
```rust
// Dropping the handle doesn't stop the task — it keeps running detached
let handle = tokio::spawn(async {
    loop {
        do_work().await;
    }
});

drop(handle);  // Task continues running in the background!
```

## Good Example
```rust
use tokio_util::sync::CancellationToken;

let token = CancellationToken::new();

let handle = tokio::spawn({
    let token = token.clone();
    async move {
        loop {
            tokio::select! {
                _ = token.cancelled() => {
                    println!("Shutting down gracefully");
                    cleanup().await;
                    break;
                }
                _ = do_work() => {}
            }
        }
    }
});

// Later: trigger cancellation
token.cancel();
handle.await?;  // Task completes cleanly
```

## Notes
- `token.clone()` is a cheap `Arc`-based clone, so every task that should respond to the same shutdown signal gets its own handle to race in `select!` without any additional synchronization.
- `token.child_token()` creates a token that is automatically cancelled whenever its parent is — the natural fit for per-connection or per-request tokens under one server-wide shutdown token, so cancelling the top-level token cascades to every child without manual bookkeeping.
- `token.is_cancelled()` is a non-blocking synchronous check for a quick guard; `token.cancelled().await` is the async form to race inside `select!` — use the synchronous form only outside an async context or when you don't want to yield.
- A `drop_guard()` (`token.clone().drop_guard()`) automatically calls `.cancel()` when the guard itself is dropped, useful for tying cancellation to a scope's lifetime (an early `return`, a panic unwind) instead of remembering to call `.cancel()` explicitly on every exit path.
- Pair with `JoinSet` for a shutdown sequence that first signals cancellation, then waits (with a timeout) for tasks to actually finish their cleanup — signaling alone doesn't guarantee tasks have stopped, only that they've been asked to.

## References
- [async-joinset-structured](async-joinset-structured.md)
- [async-select-racing](async-select-racing.md)
- [async-tokio-runtime](async-tokio-runtime.md)
