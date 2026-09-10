---
title: Use Arena Allocators for Batch Allocations
impact: MEDIUM
impactDescription: Bump-pointer allocation, O(1) bulk free
tags: [memory, allocation, arena, performance]
---

# Use Arena Allocators for Batch Allocations [MEDIUM]

## Description
Arena (bump) allocators hand out memory from a contiguous region by advancing a single pointer, and free everything at once when the arena drops. This is a natural fit for request-scoped work, parser output, or any batch of allocations that share a lifetime and die together — one AST, one HTTP request, one frame of a game loop. It replaces many individually-tracked heap allocations, each with its own bookkeeping, with a single reset at the end.

## Bad Example
```rust
// Many small allocations during parsing
fn parse(input: &str) -> Vec<Node> {
    let mut nodes = Vec::new();
    for token in tokenize(input) {
        nodes.push(Box::new(Node::new(token)));  // Heap alloc per node
    }
    nodes
}

// Per-request allocations add up
fn handle_request(req: Request) -> Response {
    let headers = parse_headers(&req);   // Allocates
    let body = parse_body(&req);         // Allocates
    generate_response()                  // Allocates
    // All freed individually at end
}
```

## Good Example
```rust
use bumpalo::Bump;

// All nodes allocated from the same arena
fn parse<'a>(input: &str, arena: &'a Bump) -> Vec<&'a Node> {
    let mut nodes = Vec::new();
    for token in tokenize(input) {
        nodes.push(arena.alloc(Node::new(token)));  // Fast bump
    }
    nodes
}  // Arena freed all at once

// Per-request arena
fn handle_request(req: Request) -> Response {
    let arena = Bump::new();
    let headers = parse_headers(&req, &arena);
    let body = parse_body(&req, &arena);
    generate_response(&arena).to_owned()  // Convert out before arena drops
}  // All request memory freed instantly
```

## Notes
- A thread-local scratch arena (reset with `.reset()` after use instead of dropped) amortizes the arena's own allocation across many batches.
- Arena reset is O(1) regardless of how many allocations were made — it just moves the bump pointer back.
- Use arenas for parsing (AST nodes), request handling, and batch processing; avoid them for long-lived data or data that must escape the arena's scope (copy it out first, as in the request example).
- The trade-off is memory, not speed: an arena wastes some capacity at the end and can outlive individually-freed data, so it is a poor fit for long-running processes with unbounded allocation patterns.
- `bumpalo::collections::Vec`/`String` let you build arena-backed collections directly, avoiding an extra copy into arena memory.
- Always measure with `criterion` before committing to an arena — the win is workload-dependent, sometimes an order of magnitude, sometimes marginal.

## References
- [mem-with-capacity](mem-with-capacity.md)
- [mem-reuse-collections](mem-reuse-collections.md)
- [bumpalo crate](https://docs.rs/bumpalo)
