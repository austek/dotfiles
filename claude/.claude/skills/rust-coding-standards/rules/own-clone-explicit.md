---
title: Use Explicit Clone for Types Where Copying Has a Cost
impact: MEDIUM
impactDescription: Makes allocation cost visible at every call site
tags: [ownership, clone, copy, api-design]
---

# Use Explicit Clone for Types Where Copying Has a Cost [MEDIUM]

## Description
Unlike `Copy`, which duplicates a value implicitly and silently, `Clone` requires an explicit `.clone()` call. That explicitness is a feature: it signals to the reader that duplication has a real cost (a heap allocation, a deep copy) at the exact point it happens. Types with heap data (`String`, `Vec`, `Box`, and structs built from them) should implement `Clone` but must not implement `Copy`, so that every duplication remains visible in the code.

## Bad Example
```rust
// Hiding an expensive operation behind an implicit move
fn process_data(data: Vec<u32>) -> Vec<u32> {
    let backup = data; // Moved, not copied - unclear at call site
    transform(backup)
}

let my_data = vec![1, 2, 3, 4, 5];
let result = process_data(my_data);
// my_data is moved - a surprise if the caller expected it to still exist
```

## Good Example
```rust
fn process_data(data: Vec<u32>) -> Vec<u32> {
    transform(data)
}

let my_data = vec![1, 2, 3, 4, 5];
let result = process_data(my_data.clone()); // Explicit: "I know this allocates"
// my_data is still available

// Better still - take a reference when ownership isn't required
fn process_data_ref(data: &[u32]) -> Vec<u32> {
    transform(data)
}
let result = process_data_ref(&my_data); // No clone needed

// For types with mixed cheap/expensive fields, a manual impl can reuse
// existing allocations via clone_from instead of allocating fresh each time
impl Clone for Document {
    fn clone(&self) -> Self {
        Self { id: self.id, content: self.content.clone(), metadata: self.metadata.clone() }
    }
    fn clone_from(&mut self, source: &Self) {
        self.id = source.id;
        self.content.clone_from(&source.content); // Reuses capacity
        self.metadata.clone_from(&source.metadata);
    }
}
```

## Notes
- Derive `Clone` when every field simply needs cloning; write a manual `impl Clone` when a field should be reset instead of duplicated (e.g. a `RefCell<Option<Cache>>` that should come back empty on clone).
- `buffer.clone_from(&source)` can reuse `buffer`'s existing capacity instead of dropping it and allocating fresh, unlike `buffer = source.clone()`.
- Before adding a clone, consider the alternatives: a reference, a `Cow` for conditional cloning, an `Arc` for cheap shared-ownership cloning, or simply taking the value by ownership so the caller moves instead of clones.

## References
- [own-copy-small](own-copy-small.md)
- [own-cow-conditional](own-cow-conditional.md)
- [own-borrow-over-clone](own-borrow-over-clone.md)
