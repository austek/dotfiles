---
title: Implement From, Not Into
impact: MEDIUM
impactDescription: One implementation gives you both From and Into for free
tags: [api-design, conversion, from, into]
---

# Implement From, Not Into [MEDIUM]

## Description
The standard library ships a blanket implementation, `impl<T, U> Into<U> for T where U: From<T>` — implementing `From<T> for U` automatically gives every caller `Into<U> for T` at no extra cost. Implementing `Into` directly instead bypasses that blanket impl, gains you nothing, and is flagged by `clippy::from_over_into` as non-idiomatic. There is effectively no case where implementing `Into` by hand is the right call for a type you own.

## Bad Example
```rust
struct UserId(u64);

// Non-idiomatic: implementing Into directly
impl Into<UserId> for u64 {
    fn into(self) -> UserId {
        UserId(self)
    }
}

// Works, but you don't get From::from() syntax, and generic code
// bounded by `T: From<u64>` won't recognize this conversion at all
let id = UserId::from(42);  // Error: From not implemented
```

## Good Example
```rust
struct UserId(u64);

// Idiomatic: implement From
impl From<u64> for UserId {
    fn from(id: u64) -> Self {
        UserId(id)
    }
}

// Both directions work automatically
let id = UserId::from(42);   // From syntax
let id: UserId = 42.into();  // Into syntax, via the blanket impl

// And an Into bound in generic code works too
fn process(id: impl Into<UserId>) {
    let id: UserId = id.into();
}
process(42u64);
```

## Notes
- `TryFrom<T>` is the fallible counterpart, with the same relationship to `TryInto` — implement `TryFrom`, get `TryInto` for free, exactly parallel to `From`/`Into`.
- Multiple `From` impls for the same target type are common and idiomatic (`From<String>`, `From<&str>` both for `Email`) — each one independently unlocks `.into()` from that source type.
- Enable `clippy::from_over_into = "warn"` in `[lints.clippy]` to catch a direct `Into` implementation automatically rather than relying on code review to spot it.
- The one legitimate exception is converting between two external types you don't own, where the orphan rules block a `From` impl in either direction — this is rare, and usually signals the conversion belongs in a newtype wrapper instead.
- Error types follow the identical pattern: implement `From<SourceError> for MyError` so `?` can convert automatically at the point of use, rather than implementing `Into<MyError> for SourceError`.

## References
- [api-impl-into](api-impl-into.md)
- [err-from-impl](err-from-impl.md)
- [api-newtype-safety](api-newtype-safety.md)
