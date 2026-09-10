---
title: Ensure Futures in select! Branches Are Cancellation-Safe
impact: CRITICAL
impactDescription: Prevents silent data loss when a losing select! branch is dropped
tags: [async, cancel-safety, select, tokio]
---

# Ensure Futures in select! Branches Are Cancellation-Safe [CRITICAL]

## Description
`tokio::select!` polls multiple futures concurrently and, the instant one branch completes, drops every other branch — along with whatever state those futures held internally. A future that was halfway through filling a buffer via `read_exact`, or halfway through draining a channel into a `Vec`, loses that partial progress silently when its branch is the one dropped. This is not a compile error; the code compiles and runs correctly most of the time, with the bug surfacing only under the specific timing where another branch happens to win the race — making it a classic hard-to-reproduce concurrency bug.

## Bad Example
```rust
use tokio::io::{AsyncReadExt, BufReader};
use tokio::net::TcpStream;
use tokio::sync::mpsc;

// Non-cancel-safe: read_exact owns an internal buffer inside the future.
// If select! drops this branch, the partially-read bytes are gone.
async fn bad_example(stream: &mut BufReader<TcpStream>, rx: &mut mpsc::Receiver<u8>) {
    let mut buf = [0u8; 1024];
    tokio::select! {
        // BUG: if the recv branch fires first, bytes already read
        // into buf inside read_exact are silently discarded
        result = stream.read_exact(&mut buf) => {
            println!("read {} bytes", result.unwrap());
        }
        msg = rx.recv() => {
            println!("got message: {:?}", msg);
        }
    }
}
```

## Good Example
```rust
use tokio::io::{AsyncReadExt, BufReader};
use tokio::net::TcpStream;
use tokio::sync::mpsc;

// Cancel-safe: the buffer lives OUTSIDE the select loop. If the recv
// branch fires, buf retains whatever was already read, and the next
// iteration continues filling it.
async fn good_example(
    stream: &mut BufReader<TcpStream>,
    rx: &mut mpsc::Receiver<u8>,
) -> std::io::Result<()> {
    let mut buf = [0u8; 1024];
    let mut filled = 0;

    loop {
        tokio::select! {
            n = stream.read(&mut buf[filled..]) => {
                // `read` (not read_exact) is cancel-safe: it either
                // reads some bytes or returns immediately.
                filled += n?;
                if filled == buf.len() { filled = 0; }
            }
            msg = rx.recv() => {
                println!("got message: {:?}", msg);
            }
        }
    }
}
```

## Notes
- Cancel-safe: `mpsc`/`broadcast`/`oneshot` receive, `watch::Receiver::changed()`, `tokio::time::sleep`, `AsyncRead::read()`, `Mutex::lock()` (the lock is simply not acquired if dropped before it completes). Not cancel-safe: `AsyncRead::read_exact()`, `AsyncRead::read_to_end()`, and any hand-written future accumulating state (like collecting into a `Vec`) internally.
- The fix pattern is almost always the same: move the accumulation state (buffer, partial `Vec`) *outside* the `select!` and into the surrounding loop's scope, so a dropped branch loses only that iteration's poll, not the accumulated progress.
- Pinning a future once with `std::pin::pin!` and reusing it across multiple `select!` iterations lets a non-cancel-safe operation survive being "raced" repeatedly, since only the `select!` polling drops, not the pinned future itself.
- Spawning the non-cancel-safe operation as its own task (`tokio::spawn`, tracked via `JoinHandle`) sidesteps the problem entirely — the task keeps running to completion even if `select!` drops its handle, since dropping a `JoinHandle` only detaches, it doesn't cancel.
- Tokio's own documentation states cancellation-safety explicitly for each primitive's `recv`/`read`/etc. method — check it rather than assuming; the property is not something you can infer from the type alone.

## References
- [async-select-racing](async-select-racing.md)
- [async-bounded-channel](async-bounded-channel.md)
- [async-no-lock-await](async-no-lock-await.md)
