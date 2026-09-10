---
title: Use Rc for Shared Ownership in Single-Threaded Code
impact: MEDIUM
impactDescription: Avoids atomic refcount overhead where thread-safety is unneeded
tags: [ownership, rc, performance, single-threaded]
---

# Use Rc for Shared Ownership in Single-Threaded Code [MEDIUM]

## Description
`Rc<T>` (Reference Counted) provides shared ownership without the atomic overhead of `Arc<T>`. In single-threaded code, `Rc` is faster because it uses plain (non-atomic) reference counting. Reaching for `Arc` when the code never crosses a thread boundary spends CPU cycles on synchronization that buys nothing — `Rc` is `!Send + !Sync`, so the compiler itself enforces that it never leaks across threads.

## Bad Example
```rust
use std::sync::Arc;

// Single-threaded application using Arc unnecessarily
fn build_tree() -> Arc<Node> {
    let root = Arc::new(Node::new("root"));
    let child1 = Arc::new(Node::new("child1"));
    let child2 = Arc::new(Node::new("child2"));

    // All in the same thread, but paying atomic overhead anyway
    root.add_child(child1.clone());
    root.add_child(child2.clone());
    root
}
```

## Good Example
```rust
use std::rc::{Rc, Weak};
use std::cell::RefCell;

// Single-threaded: use Rc for zero atomic overhead
fn build_tree() -> Rc<Node> {
    let root = Rc::new(Node::new("root"));
    let child1 = Rc::new(Node::new("child1"));
    root.add_child(Rc::clone(&child1)); // Rc::clone(&x) makes the refcount bump explicit
    root
}

// Weak breaks reference cycles for back-references (e.g. child -> parent)
struct Node {
    parent: RefCell<Weak<Node>>,      // does not keep the parent alive
    children: RefCell<Vec<Rc<Node>>>,
}

let parent = Rc::new(Node { parent: RefCell::new(Weak::new()), children: RefCell::new(vec![]) });
let child = Rc::new(Node { parent: RefCell::new(Rc::downgrade(&parent)), children: RefCell::new(vec![]) });
parent.children.borrow_mut().push(Rc::clone(&child));

// upgrade() yields Option<Rc<Node>> - None once the parent is dropped
let _maybe_parent: Option<Rc<Node>> = child.parent.borrow().upgrade();
```

## Notes
- Decision guide: single-threaded shared ownership → `Rc<T>`; multi-threaded → `Arc<T>`; library code with an unknown threading model → default to `Arc<T>` as the safer choice.
- `Rc` never frees a value caught in a reference cycle since the strong count never reaches zero — use `Weak<T>` for back-references (a child pointing at its parent) so the cycle can be collected.
- `Rc<T>` gives shared *immutable* access; pair it with `RefCell<T>` (`Rc<RefCell<T>>`) when the shared value also needs interior mutability in single-threaded code.

## References
- [own-arc-shared](own-arc-shared.md)
- [own-refcell-interior](own-refcell-interior.md)
