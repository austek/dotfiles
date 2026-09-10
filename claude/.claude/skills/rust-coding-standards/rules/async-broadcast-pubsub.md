---
title: Use broadcast for Pub/Sub Where All Subscribers See All Messages
impact: MEDIUM
impactDescription: Delivers every message to every subscriber independently
tags: [async, channels, broadcast, pubsub]
---

# Use broadcast for Pub/Sub Where All Subscribers See All Messages [MEDIUM]

## Description
`mpsc` delivers each message to exactly one consumer, competing among however many receivers exist. `broadcast` is the opposite shape: every subscriber gets every message independently, which is exactly what event notification needs — a logger and a metrics collector both need to see the same `UserLoggedIn` event, not race for it. Each `broadcast::Sender::subscribe()` call creates an independent `Receiver` with its own read position into the channel's buffer.

## Bad Example
```rust
use tokio::sync::mpsc;

// mpsc only delivers to ONE consumer — the second subscriber has no
// way to also receive every message
let (tx, mut rx) = mpsc::channel::<Event>(100);
// Can't clone the receiver to get a second independent stream
```

## Good Example
```rust
use tokio::sync::broadcast;

// broadcast delivers to ALL subscribers
let (tx, _) = broadcast::channel::<Event>(100);

let mut rx1 = tx.subscribe();
let mut rx2 = tx.subscribe();

tokio::spawn(async move {
    while let Ok(event) = rx1.recv().await {
        handle_in_logger(event);
    }
});

tokio::spawn(async move {
    while let Ok(event) = rx2.recv().await {
        handle_in_metrics(event);
    }
});

// Both subscribers receive this
tx.send(Event::UserLogin { user_id: 42 })?;
```

## Notes
- A slow subscriber that falls more than the buffer size behind gets `Err(RecvError::Lagged(count))` on its next `recv()` — this is not a channel failure, it's the mechanism telling you the subscriber missed `count` messages; log it and keep receiving rather than treating it as fatal.
- `Err(RecvError::Closed)` means every sender has been dropped — the correct terminal condition for the subscriber's receive loop.
- `broadcast` requires the message type to be `Clone`, since each subscriber gets its own copy — wrap large or non-`Clone` payloads in `Arc<T>` rather than forcing every message type to implement `Clone` expensively.
- Choose `broadcast` over `watch` when subscribers need the full history of events (logs, notifications); choose `watch` instead when subscribers only care about the current value and can safely skip anything superseded (config, status) — a slow `broadcast` subscriber lags, a slow `watch` subscriber just jumps to the latest value.
- An `EventBus` wrapper struct holding just the `Sender` (with `publish()` and `subscribe()` methods) is a common way to hide the raw channel API behind a small, purpose-built interface for application event distribution.

## References
- [async-mpsc-queue](async-mpsc-queue.md)
- [async-watch-latest](async-watch-latest.md)
- [async-bounded-channel](async-bounded-channel.md)
