---
title: Pre-allocate With with_capacity When Size Is Known
impact: HIGH
impactDescription: Eliminates repeated reallocation-and-copy as a collection grows
tags: [memory, allocation, capacity, performance]
---

# Pre-allocate With with_capacity When Size Is Known [HIGH]

## Description
An empty `Vec::new()`, `String::new()`, or `HashMap::new()` starts with zero capacity and grows by reallocating and copying every existing element each time it runs out of room — typically doubling, so filling a collection to size N costs roughly log₂(N) reallocations, each one copying everything built so far. When the final size is known or can be reasonably estimated ahead of time, `with_capacity(n)` allocates once up front, turning that reallocation churn into a single allocation.

## Bad Example
```rust
// Vec starts at capacity 0, reallocates at 4, 8, 16, 32... — roughly
// 10 reallocations, each copying everything collected so far
let mut results = Vec::new();
for i in 0..1000 {
    results.push(process(i));
}

// HashMap's default capacity is small too
let mut map = HashMap::new();
for (k, v) in pairs {  // Many reallocations as it grows
    map.insert(k, v);
}
```

## Good Example
```rust
// Pre-allocate the exact size: zero reallocations
let mut results = Vec::with_capacity(1000);
for i in 0..1000 {
    results.push(process(i));
}

// Or let collect() use the iterator's size hint automatically
let results: Vec<_> = (0..1000).map(process).collect();

// Pre-allocate a HashMap from a known pair count
let mut map = HashMap::with_capacity(pairs.len());
for (k, v) in pairs {
    map.insert(k, v);
}
```

## Notes
- `.collect()` already consults the source iterator's `size_hint()` to pre-allocate when the hint is exact (e.g. collecting from a `Vec` or a `Range`), so an explicit `with_capacity` mainly matters when you build the collection with a manual loop instead of `collect()`.
- Estimate rather than guess when the exact size is unknown: for a filter step, `items.len() / expected_pass_rate` beats no estimate at all; for joining strings, sum the part lengths plus separator overhead before allocating.
- `.reserve(n)` grows existing capacity by at least `n` more without discarding what's already there; `.reserve_exact(n)` avoids the extra headroom the default strategy typically adds; `.shrink_to_fit()` releases capacity the collection no longer needs.
- Skip pre-allocation for genuinely unknown or small expected sizes — the code complexity and the risk of over-allocating (wasted memory if the estimate is wrong) can outweigh the reallocation savings.
- Real-world evidence: `fd` (the file finder) pre-allocates its directory-entry receive buffer with a fixed `with_capacity(MAX_BUFFER_LENGTH)` rather than growing it per batch, precisely to avoid reallocation on its hot path.

## References
- [mem-reuse-collections](mem-reuse-collections.md)
- [mem-smallvec](mem-smallvec.md)
