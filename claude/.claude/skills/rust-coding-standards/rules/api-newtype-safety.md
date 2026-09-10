---
title: Use Newtypes to Prevent Mixing Semantically Different Values
impact: HIGH
impactDescription: Turns argument-swap bugs into compile errors
tags: [api-design, newtype, type-safety, ids]
---

# Use Newtypes to Prevent Mixing Semantically Different Values [HIGH]

## Description
A raw primitive like `u64` or `String` carries no semantic meaning the compiler can check — a function taking `(u64, u64)` compiles identically whether the arguments are in the right order or swapped. Wrapping each distinct concept in its own newtype (`UserId(u64)`, `GroupId(u64)`) gives the compiler enough information to reject a mismatched call at the call site, turning a silent runtime bug (or a bug that ships) into a compile error, at zero runtime cost — the newtype has the identical layout and size as the primitive it wraps.

## Bad Example
```rust
struct User {
    id: u64,
    group_id: u64,
    created_at: u64,  // Unix timestamp
}

fn add_user_to_group(user_id: u64, group_id: u64) { ... }

// Bug: arguments swapped — compiles fine, fails at runtime
add_user_to_group(user.group_id, user.id);

// Bug: wrong field entirely — also compiles fine
add_user_to_group(user.created_at, user.group_id);
```

## Good Example
```rust
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
struct UserId(u64);

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
struct GroupId(u64);

struct User {
    id: UserId,
    group_id: GroupId,
}

fn add_user_to_group(user_id: UserId, group_id: GroupId) { ... }

// Compile error: expected UserId, found GroupId
add_user_to_group(user.group_id, user.id);
```

## Notes
- Newtypes are zero-cost: `size_of::<Miles>() == size_of::<f64>()` holds for any single-field tuple struct, so the safety comes with no runtime overhead — the compiler erases the wrapper entirely in release builds.
- Derive only the traits the newtype actually needs — a minimal ID type might need only `Debug, Clone, Copy`; a `HashMap` key needs `PartialEq, Eq, Hash` too; `#[serde(transparent)]` makes a newtype serialize identically to its inner value when that's the desired wire format.
- Pair a newtype with a validating constructor (`Email::new(s) -> Result<Self, EmailError>`) when not just the *kind* but the *content* needs enforcing — see `api-parse-dont-validate` for that extension of the same idea.
- Best return on investment: IDs that could be confused with each other, units that shouldn't mix (`Celsius` vs `Fahrenheit`), and different meanings of the same primitive type (`Milliseconds` vs `Seconds`). Skip it for a single-use value with no plausible confusion — `struct X(i32)` wrapping a genuinely private, unambiguous counter is unneeded ceremony.
- An explicit `impl From<Kilometers> for Miles` makes an intentional unit conversion visible at the call site (`drive(km.into())`), rather than letting two conceptually different quantities interconvert implicitly.

## References
- [api-parse-dont-validate](api-parse-dont-validate.md)
- [own-copy-small](own-copy-small.md)
