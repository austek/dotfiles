---
title: Clear and Reuse Collections Instead of Recreating Them in Loops
impact: MEDIUM
impactDescription: Removes repeated allocate/deallocate cycles from hot loops
tags: [memory, allocation, loop, reuse]
---

# Clear and Reuse Collections Instead of Recreating Them in Loops [MEDIUM]

## Description
Allocating a fresh `Vec`, `String`, or `HashMap` inside a loop body generates allocator pressure on every iteration, even though the collection's capacity could be reused. Moving the collection's creation outside the loop and calling `.clear()` at the top of each iteration keeps its existing capacity and resets only the length — turning repeated allocate/deallocate cycles into a single allocation reused for the loop's whole lifetime.

## Bad Example
```rust
fn process_batches(batches: &[Batch]) -> Vec<Result> {
    let mut results = Vec::new();

    for batch in batches {
        let mut temp = Vec::new();  // Allocates every iteration
        for item in &batch.items {
            temp.push(transform(item));
        }
        results.push(aggregate(&temp));
        // temp dropped here — deallocation, then reallocation next loop
    }
    results
}
```

## Good Example
```rust
fn process_batches(batches: &[Batch]) -> Vec<Result> {
    let mut results = Vec::with_capacity(batches.len());
    let mut temp = Vec::new();  // Allocate once, outside the loop

    for batch in batches {
        temp.clear();  // Reuses allocation, just resets length
        for item in &batch.items {
            temp.push(transform(item));
        }
        results.push(aggregate(&temp));
        // temp keeps its capacity for the next iteration
    }
    results
}
```

## Notes
- `.clear()` keeps capacity and is O(n) only for types that run `Drop`; `.truncate(n)` keeps the first `n` elements; `.drain(..)` returns an iterator over the removed elements while also clearing — pick based on whether you need the removed values.
- Assigning `vec = Vec::new()` inside a loop discards the accumulated capacity just as surely as letting the old `Vec` drop — the fix is `.clear()`, not a fresh literal.
- The same pattern applies to `HashMap` (`.clear()` keeps bucket allocations) and to a reusable `String` buffer combined with `write!()` instead of `format!()` on each iteration.
- Skip this pattern when ownership must transfer out of the loop (each inner `Vec` is genuinely independent and moved into a result) or across threads without shared access — reuse only helps when the same buffer can safely serve every iteration.
- `BufWriter` already applies this idea internally; pairing it with your own reusable formatting buffer avoids allocation on both the formatting and I/O side of a write-heavy loop.

## References
- [mem-with-capacity](mem-with-capacity.md)
- [mem-clone-from](mem-clone-from.md)
- [mem-write-over-format](mem-write-over-format.md)
