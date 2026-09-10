---
title: Use mem::take / mem::replace to Move Out of &mut Without Cloning
impact: HIGH
impactDescription: Zero-copy move where the borrow checker would otherwise force a clone
tags: [memory, ownership, mem-take, mem-replace]
---

# Use mem::take / mem::replace to Move Out of &mut Without Cloning [HIGH]

## Description
Rust's ownership rules forbid moving a field out of a `&mut self` reference, because the compiler must guarantee the field is never left in an invalid state. The common workaround is `.clone()`, which allocates unnecessarily just to satisfy the borrow checker. `std::mem::take` swaps the field with `T::default()` and returns the original value; `std::mem::replace` swaps in an explicit replacement of your choosing. Both are zero-copy: no allocation, just a few register moves, and both leave the field in a valid state so `Drop` and subsequent access stay sound.

## Bad Example
```rust
struct Processor {
    items: Vec<String>,
}

impl Processor {
    // Clones the entire Vec just to drain it — unnecessary allocation
    fn flush(&mut self) -> Vec<String> {
        let v = self.items.clone();
        self.items.clear();
        v
    }
}
```

## Good Example
```rust
use std::mem;

struct Processor {
    items: Vec<String>,
}

impl Processor {
    // Moves the Vec out in one step, leaving an empty Vec behind
    fn flush(&mut self) -> Vec<String> {
        mem::take(&mut self.items)
    }
}
```

## Notes
- `mem::take(&mut x)` is shorthand for `mem::replace(&mut x, Default::default())` — use `replace` directly when the field's next value isn't the type's default, such as transitioning a state-machine `enum` field to an explicit next variant.
- `mem::take` requires `T: Default`; for types with no meaningful default, wrap in `Option<T>` and call `.take()` (the `Option::take` method, same underlying idea) to get `None` back cleanly.
- This is the idiomatic way to move a field out inside `Drop::drop`, where only `&mut self` is available and the field must still be left in a valid, safely-droppable state afterward.
- Both functions are `#[inline]` and compile to a handful of moves with no heap involvement — there is no performance reason to prefer `.clone()` once the borrow-checker constraint is understood.
- A `mem::replace` inside a `match` is a common state-machine pattern: replace the field with its next state, then match on the *returned* old state to decide what follow-up work (like logging a transition) to do.

## References
- [own-move-large](own-move-large.md)
- [mem-clone-from](mem-clone-from.md)
- [own-borrow-over-clone](own-borrow-over-clone.md)
