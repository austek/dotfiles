---
title: Use Sealed Traits to Prevent External Implementations
impact: HIGH
impactDescription: Lets you add trait methods later without a breaking change
tags: [api-design, sealed-trait, semver, traits]
---

# Use Sealed Traits to Prevent External Implementations [HIGH]

## Description
A public trait can be implemented by anyone, which is fine for extension points but a liability when you need to guarantee every implementation behaves correctly, or when you expect to add methods in a future version. Adding a required method to a public trait breaks every external implementation that doesn't have it — a sealed trait sidesteps this entirely: external code can *use* the trait (call its methods, take it as a bound) but cannot *implement* it, because implementing it requires also implementing a private supertrait that only your crate can name.

## Bad Example
```rust
// Anyone can implement this trait
pub trait DatabaseDriver {
    fn connect(&self, url: &str) -> Connection;
}

// Later, you want to add a required method — BREAKING CHANGE for every
// external implementor, since none of them have this method
pub trait DatabaseDriver {
    fn connect(&self, url: &str) -> Connection;
    fn transaction(&self) -> Transaction;  // External impls now fail to compile
}
```

## Good Example
```rust
// A private module holds a private supertrait
mod private {
    pub trait Sealed {}
}

// The public trait requires the private one
pub trait DatabaseDriver: private::Sealed {
    fn connect(&self, url: &str) -> Connection;
}

// Only this crate can implement Sealed, thus DatabaseDriver
pub struct PostgresDriver;
impl private::Sealed for PostgresDriver {}
impl DatabaseDriver for PostgresDriver {
    fn connect(&self, url: &str) -> Connection { todo!() }
}

// External crates cannot implement it — private::Sealed is inaccessible
// impl DatabaseDriver for ExternalDriver { }  // Error!

// But external code CAN still use the trait as a bound
fn use_driver(driver: &impl DatabaseDriver) {
    let _conn = driver.connect("postgres://localhost");
}
```

## Notes
- Sealing buys you the ability to add new required methods later without a breaking change — since no external code has an implementation to break, only your own crate's implementations need updating.
- A default method body on a sealed trait lets you add functionality that automatically applies to all existing implementors with zero changes to them, while still reserving the right to override per-implementor later.
- Use sealing when implementation correctness is hard to get right externally (a database driver, a safety-critical parser) or when the trait functions partly as an internal marker — not for a trait meant as a genuine extension point, where blocking external implementations defeats the trait's purpose.
- A "partially sealed" variant is possible: seal only the core methods that must stay internally consistent, and leave other methods with default implementations open for external override — this gives some customization without full exposure.
- `#[non_exhaustive]` solves the equivalent problem for enums and structs (forward-compatible evolution); sealed traits are the trait-shaped version of the same underlying concern.

## References
- [api-non-exhaustive](api-non-exhaustive.md)
- [api-extension-trait](api-extension-trait.md)
- [api-typestate](api-typestate.md)
