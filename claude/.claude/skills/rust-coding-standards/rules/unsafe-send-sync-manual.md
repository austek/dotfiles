---
title: Document Invariants When Manually Implementing Send or Sync
impact: CRITICAL
impactDescription: An undocumented manual impl is an unauditable data-race liability
tags: [unsafe, send, sync, concurrency]
---

# Document Invariants When Manually Implementing Send or Sync [CRITICAL]

## Description
`Send` and `Sync` are unsafe auto-traits. The compiler derives them automatically and correctly for the vast majority of types by inspecting their fields — a manual implementation signals that the borrow checker *cannot* verify the invariant on its own, and the programmer is asserting it by hand. Get it wrong and the result is a data race that no amount of safe-code review will ever catch, because the type system now believes something false. An `unsafe impl Send`/`Sync` with no explanation is a liability: the next person to add a field may silently invalidate the invariant without realizing the impl depends on it.

## Bad Example
```rust
use std::cell::Cell;

// Cell<T> is !Sync because it allows non-atomic interior mutation.
// This manual impl removes that protection with no explanation at all.
struct SharedCounter {
    value: Cell<u32>,
}

unsafe impl Sync for SharedCounter {} // data race waiting to happen — no SAFETY comment
unsafe impl Send for SharedCounter {} // likewise
```

## Good Example
```rust
use std::marker::PhantomData;
use std::sync::Mutex;

// Prefer opting OUT of Send/Sync via PhantomData when a type logically
// owns a non-owning raw pointer — no unsafe impl needed at all.
struct IntrusiveRef<T> {
    ptr: *const T,
    _marker: PhantomData<*const T>, // makes this !Send + !Sync, matching *const T
}

/// A buffer owned exclusively by one thread at a time. The raw pointer
/// always points to a heap allocation this struct owns; no other
/// reference to that allocation exists outside this struct.
struct OwnedBuffer {
    ptr: *mut u8,
    len: usize,
}

// SAFETY: OwnedBuffer owns its allocation exclusively (no aliasing), and
// access is protected by the caller's Mutex<OwnedBuffer> at usage sites.
unsafe impl Send for OwnedBuffer {}

// SAFETY: OwnedBuffer exposes no shared mutation — every method requires
// &mut self, so concurrent & references cannot mutate the buffer.
unsafe impl Sync for OwnedBuffer {}

// Prefer wrapping in Arc<Mutex<T>> over manual impls wherever possible —
// the compiler derives Send + Sync for free.
struct SafeCounter {
    value: Mutex<u32>,
}
```

## Notes
- Auto-derive first: if a type's fields are entirely `Send`/`Sync` already, the compiler grants the traits for free — reserve manual impls for types touching raw pointers, `Cell`, or other explicitly non-auto types.
- `PhantomData<*const T>` is the canonical way to make a type `!Send + !Sync` without any `unsafe`, since `*const T` already lacks both traits and the marker propagates that automatically; `PhantomData<*mut T>` does the same while also marking the type as invariant over `T`.
- Every `unsafe impl Send`/`Sync` must carry a `// SAFETY:` comment naming the specific invariant being upheld and why it holds — "trust me" is not an invariant.
- Adding `unsafe impl Send` to a type containing an `Rc<T>` or a bare `Cell<T>` is almost always unsound — reach for `Arc<T>` and `Mutex<T>`/`RwLock<T>` instead of overriding the compiler's judgment.
- A manual impl is a promise about every current *and future* field — revisit it whenever the struct's fields change, since the compiler will not re-verify a hand-written impl for you.

## References
- [unsafe-safety-comment](unsafe-safety-comment.md)
- [own-arc-shared](own-arc-shared.md)
- [own-mutex-interior](own-mutex-interior.md)
