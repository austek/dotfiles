---
title: Rely on Lifetime Elision Rules
impact: LOW
impactDescription: Cleaner signatures with no loss of precision
tags: [ownership, lifetimes, readability, api-design]
---

# Rely on Lifetime Elision Rules [LOW]

## Description
Rust's lifetime elision rules handle most common borrowing patterns automatically. Writing out explicit lifetimes where elision already applies clutters signatures without adding any clarity or safety. Understanding exactly when elision applies — and when it doesn't — lets you know when an explicit lifetime is genuinely required versus when it's just noise.

## Bad Example
```rust
// Unnecessary explicit lifetimes - elision handles all of these
fn first_word<'a>(s: &'a str) -> &'a str {
    s.split_whitespace().next().unwrap_or("")
}

fn get_name<'a>(person: &'a Person) -> &'a str {
    &person.name
}

impl<'a> Display for Wrapper<'a> {
    fn fmt<'b>(&'b self, f: &'b mut Formatter<'_>) -> fmt::Result {
        write!(f, "{}", self.0)
    }
}
```

## Good Example
```rust
// Let elision do its job
fn first_word(s: &str) -> &str {
    s.split_whitespace().next().unwrap_or("")
}

fn get_name(person: &Person) -> &str {
    &person.name
}

impl Display for Wrapper<'_> {
    fn fmt(&self, f: &mut Formatter<'_>) -> fmt::Result {
        write!(f, "{}", self.0)
    }
}
```

## Notes
- The three elision rules: (1) each elided input reference gets its own distinct lifetime; (2) with exactly one input reference, the output gets that same lifetime; (3) for a method taking `&self`/`&mut self`, the output gets `self`'s lifetime.
- Explicit lifetimes are still required when a function takes multiple input references and the output could plausibly borrow from any of them (`fn longest<'a>(x: &'a str, y: &'a str) -> &'a str`), and whenever a struct holds a reference as a field.
- Use the anonymous lifetime `'_` in signatures and impls where a lifetime parameter exists but doesn't need to be named — it documents that a lifetime is present without adding elision-defeating verbosity.

## References
- [own-borrow-over-clone](own-borrow-over-clone.md)
