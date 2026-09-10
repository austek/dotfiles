---
title: Parse Into Validated Types at Boundaries
impact: HIGH
impactDescription: Makes invalid states unrepresentable instead of merely unlikely
tags: [api-design, validation, type-safety, boundaries]
---

# Parse Into Validated Types at Boundaries [HIGH]

## Description
Validating a raw `&str` and hoping every caller remembers to check it again before use scatters the same validation logic across a codebase, and it only takes one forgotten check for invalid data to reach a sensitive operation. Parsing the raw input into a type that can *only* be constructed from valid data — an `Email` whose sole constructor is a fallible `parse()` — makes the type system the enforcer: once you hold an `Email`, there is no code path by which it could be invalid, because an invalid one was never representable in the first place.

## Bad Example
```rust
fn send_email(email: &str) -> Result<(), Error> {
    // Did someone validate this already? Who knows.
    if !is_valid_email(email) {
        return Err(Error::InvalidEmail);
    }
    smtp_send(email)
}

fn process_user_email(email: &str) {
    // Oops, no validation here — and nothing stops this from compiling
    database.store_email(email);
}
```

## Good Example
```rust
/// A validated email address. Can only be constructed via `Email::parse()`.
#[derive(Debug, Clone, PartialEq, Eq, Hash)]
pub struct Email(String);

impl Email {
    pub fn parse(s: impl Into<String>) -> Result<Self, EmailError> {
        let s = s.into();
        if s.contains('@') && s.len() > 3 {
            Ok(Email(s))
        } else {
            Err(EmailError::Invalid)
        }
    }

    pub fn as_str(&self) -> &str {
        &self.0
    }
}

// Functions accepting Email need no validation — it's already guaranteed
fn send_email(email: &Email) -> Result<(), Error> {
    smtp_send(email.as_str())
}

// Parse at the system boundary, work with validated types afterward
fn handle_request(raw: RawRequest) -> Result<Response, Error> {
    let email = Email::parse(&raw.email)?;
    process_user(email)
}
```

## Notes
- Parse every external input at the boundary where it enters your system — an HTTP handler, a CLI argument parser, a config-file loader — and pass validated types (`Email`, `Port`, `NonEmptyString`, `Percentage`) through the rest of the call graph, never the raw form again.
- A private field plus a public fallible constructor is the whole mechanism: `pub struct Email(String)` with the field not `pub`, and `pub fn parse(...) -> Result<Self, E>` as the only way in — there is no back door that skips validation.
- `sqlx`'s `query!` macro takes this to its logical extreme, parsing and validating SQL *at compile time* — if the query is invalid, the crate does not compile, making an invalid SQL string entirely unrepresentable in a working build.
- Pair the validated type with `Display`/`AsRef<str>` so it remains as easy to print or borrow-as-a-string as the raw type was — validation should not make the type awkward to use downstream.
- `TryFrom` is a natural mechanical fit for the same idea when the conversion is a type-to-type transformation rather than parsing free-form text — implement `TryFrom<i32> for PositiveInt` instead of a bespoke `parse` method when a `From`-like signature fits better.

## References
- [api-newtype-safety](api-newtype-safety.md)
- [api-typestate](api-typestate.md)
