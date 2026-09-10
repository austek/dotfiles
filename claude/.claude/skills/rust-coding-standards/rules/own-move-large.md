---
title: Move Large Types via Box Instead of Copying
impact: MEDIUM
impactDescription: Reduces move cost from a full memcpy to a single pointer copy
tags: [ownership, box, performance, memory]
---

# Move Large Types via Box Instead of Copying [MEDIUM]

## Description
In Rust, "moving" a value means copying its bytes to a new location and invalidating the old binding. For large types — hundreds of bytes or more — that memcpy is real work, repeated every time the value is passed by value or returned. Boxing a large type reduces the move cost to copying a single pointer (8 bytes) regardless of how large the boxed data actually is, at the cost of one heap allocation when the `Box` is first created.

## Bad Example
```rust
// Large struct moved repeatedly = expensive memcpy each time
struct GameState {
    board: [[Cell; 100]; 100],  // 10,000 cells
    history: [Move; 1000],      // 1,000 moves
    players: [Player; 4],
    // Total: potentially tens of KB
}

fn process_state(state: GameState) -> GameState {
    let mut new_state = state;  // Memcpy here
    new_state.apply_rules();
    new_state                   // Memcpy on return
}
```

## Good Example
```rust
// Box reduces move cost to 8 bytes
struct GameState {
    board: Box<[[Cell; 100]; 100]>, // Pointer to heap
    history: Vec<Move>,             // Already heap-allocated
    players: [Player; 4],
}

fn process_state(mut state: GameState) -> GameState {
    state.apply_rules(); // Moving just pointers + small inline data
    state                // Cheap move
}

// Alternative: avoid the move entirely by borrowing
fn analyze_state(state: &GameState) -> Analysis {
    compute_analysis(state) // No copying at all
}
```

## Notes
- Sizing guide: under ~128 bytes, don't bother boxing; 128-512 bytes, box only if the value moves frequently; above ~512 bytes (and especially above 4KB), box it or pass by reference.
- Prefer a plain reference (`&T`/`&mut T`) over boxing when the caller doesn't actually need ownership transfer — that avoids both the memcpy and the heap allocation.
- Don't box preemptively. Confirm the type's size with `std::mem::size_of::<T>()` and profile (e.g. with `cargo flamegraph` or `perf`) before concluding that moves are an actual bottleneck.

## References
- [own-copy-small](own-copy-small.md)
- [own-borrow-over-clone](own-borrow-over-clone.md)
