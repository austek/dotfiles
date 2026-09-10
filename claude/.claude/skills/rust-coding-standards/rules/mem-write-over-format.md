---
title: Use write! Into Existing Buffers Instead of format! Allocations
impact: MEDIUM
impactDescription: Reuses buffer capacity instead of allocating per call
tags: [memory, format, write, allocation]
---

# Use write! Into Existing Buffers Instead of format! Allocations [MEDIUM]

## Description
`format!()` always allocates a fresh `String` to hold its result. `write!()` instead writes formatted output directly into an existing, mutable buffer — a `String` via `std::fmt::Write`, or a `Vec<u8>`/file/socket via `std::io::Write` — reusing whatever capacity that buffer already has. In hot loops or high-frequency logging, replacing a `format!()`-then-push pattern with `write!()` into a buffer you clear and reuse each iteration removes the per-call allocation entirely after the first pass.

## Bad Example
```rust
fn log_event(event: &Event, output: &mut Vec<u8>) {
    // format! allocates a new String on every call
    let line = format!(
        "[{}] {}: {}\n",
        event.timestamp, event.level, event.message
    );
    output.extend_from_slice(line.as_bytes());
}

fn build_response(items: &[Item]) -> String {
    let mut result = String::new();
    for item in items {
        // format! allocates for each item before the push_str copies it again
        result.push_str(&format!("{}: {}\n", item.name, item.value));
    }
    result
}
```

## Good Example
```rust
use std::fmt::Write;

fn build_response(items: &[Item]) -> String {
    let mut result = String::with_capacity(items.len() * 64);
    for item in items {
        // Writes directly into result's existing capacity — no intermediate String
        write!(&mut result, "{}: {}\n", item.name, item.value).unwrap();
    }
    result
}

// Reusable formatting buffer, cleared and reused across calls
struct Formatter {
    buffer: String,
}

impl Formatter {
    fn format_event(&mut self, event: &Event) -> &str {
        self.buffer.clear();  // Reuse allocation
        write!(&mut self.buffer, "[{}] {}", event.timestamp, event.message).unwrap();
        &self.buffer
    }
}
```

## Notes
- `std::fmt::Write` targets `String`/`&mut String`; `std::io::Write` targets `Vec<u8>`, `File`, `TcpStream`, and similar byte sinks — both traits are named `Write`, so import only the one you need or alias with `as`.
- Both traits return `Result`, even though writing into a `String` or `Vec<u8>` never actually fails — `.unwrap()` there is idiomatic, not a sign of missing error handling.
- `writeln!()` appends a trailing newline automatically, equivalent to `write!(..., "{}\n", ...)` but harder to typo.
- `format!()` remains the right choice for one-time formatting outside a loop, or whenever the function must return an owned `String` anyway and there's no pre-existing buffer to reuse.
- Wrapping a reusable buffer in a small `Formatter` struct that `.clear()`s before each `write!` turns a series of allocating calls into a single allocation amortized across the whole call sequence.

## References
- [mem-avoid-format](mem-avoid-format.md)
- [mem-reuse-collections](mem-reuse-collections.md)
- [mem-with-capacity](mem-with-capacity.md)
