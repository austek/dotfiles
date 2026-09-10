---
title: Use Bounded Channels to Apply Backpressure
impact: CRITICAL
impactDescription: Prevents unbounded memory growth when producers outpace consumers
tags: [async, channels, backpressure, tokio]
---

# Use Bounded Channels to Apply Backpressure [CRITICAL]

## Description
An unbounded channel grows without limit whenever producers outpace consumers, and in production that growth ends in memory exhaustion, not a graceful slowdown. A bounded channel caps its buffer at a fixed size and makes `send` an async operation that waits when the buffer is full — producers are naturally throttled to the consumer's actual processing rate. This turns an unbounded, unpredictable failure mode (OOM under load) into a predictable, capped one (bounded memory, and a visible point where backpressure kicks in).

## Bad Example
```rust
use tokio::sync::mpsc;

// Unbounded channel — can grow forever
let (tx, mut rx) = mpsc::unbounded_channel::<Message>();

tokio::spawn(async move {
    loop {
        let msg = generate_message();
        tx.send(msg).unwrap();  // Never blocks, never fails (until OOM)
    }
});

tokio::spawn(async move {
    while let Some(msg) = rx.recv().await {
        slow_process(msg).await;  // Can't keep up
    }
});
// Memory grows unboundedly until crash
```

## Good Example
```rust
use tokio::sync::mpsc;

// Bounded channel — backpressure when full
let (tx, mut rx) = mpsc::channel::<Message>(100);  // Max 100 items

tokio::spawn(async move {
    loop {
        let msg = generate_message();
        // Blocks if the channel is full — natural backpressure
        tx.send(msg).await.unwrap();
    }
});

tokio::spawn(async move {
    while let Some(msg) = rx.recv().await {
        slow_process(msg).await;
    }
});
// Memory usage capped at ~100 messages
```

## Notes
- Size the buffer from the expected burst size, then measure actual usage in production and adjust — too small causes frequent blocking and reduced throughput, too large delays backpressure and wastes memory in the meantime.
- `try_send` returns `Err(TrySendError::Full(msg))` immediately instead of waiting, letting you drop or redirect a message rather than block the producer — appropriate when losing a message under load is preferable to stalling it.
- `tx.reserve().await` reserves a guaranteed send slot before you've built the message, useful when constructing the message itself is expensive and you don't want to pay that cost only to find the channel full.
- `oneshot` is the right choice for a single value between one producer and one consumer; `broadcast` when every subscriber must see every message; `watch` when subscribers only care about the latest value — reach for `mpsc` specifically for the many-producers/single-consumer work-queue shape.
- A worker-pool pattern (several tasks pulling from one bounded channel behind a shared `Mutex`) combines backpressure with parallel consumption, useful when a single consumer can't keep up with even a throttled producer.

## References
- [async-mpsc-queue](async-mpsc-queue.md)
- [async-oneshot-response](async-oneshot-response.md)
- [async-watch-latest](async-watch-latest.md)
