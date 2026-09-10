---
title: Define Custom Error Types for Domain-Specific Failures
impact: HIGH
impactDescription: Lets callers pattern-match on specific failure modes
tags: [error-handling, api-design, thiserror, types]
---

# Define Custom Error Types for Domain-Specific Failures [HIGH]

## Description
Generic errors like `String`, `Box<dyn Error>`, or an untyped catch-all obscure what can actually go wrong. A custom error type documents every failure mode in the type system, lets callers pattern-match to handle specific cases differently, and gives the API a clear, self-documenting contract instead of a wall of stringly-typed messages the caller must parse or substring-match.

## Bad Example
```rust
// Generic string errors - no structure
fn validate_user(user: &User) -> Result<(), String> {
    if user.name.is_empty() {
        return Err("Name is empty".to_string());
    }
    if user.age > 150 {
        return Err("Age is invalid".to_string());
    }
    Ok(())
}

// Caller can't match on specific errors
match validate_user(&user) {
    Ok(()) => save(user),
    Err(msg) => {
        if msg.contains("Name") { prompt_for_name() } // Fragile string matching!
    }
}
```

## Good Example
```rust
use thiserror::Error;

#[derive(Error, Debug)]
pub enum ValidationError {
    #[error("name cannot be empty")]
    EmptyName,
    #[error("name exceeds maximum length of {max} characters")]
    NameTooLong { max: usize, actual: usize },
    #[error("invalid age {0}: must be between 0 and 150")]
    InvalidAge(u8),
}

fn validate_user(user: &User) -> Result<(), ValidationError> {
    if user.name.is_empty() {
        return Err(ValidationError::EmptyName);
    }
    if user.age > 150 {
        return Err(ValidationError::InvalidAge(user.age));
    }
    Ok(())
}

// Caller can match specifically, no string parsing
match validate_user(&user) {
    Ok(()) => save(user),
    Err(ValidationError::EmptyName) => prompt_for_name(),
    Err(ValidationError::InvalidAge(age)) => {
        show_error(&format!("Please enter a valid age (you entered {})", age))
    }
    Err(e) => show_error(&e.to_string()),
}
```

## Notes
- Group related failures into one domain-specific enum per concern (`AuthError`, `PaymentError`, `FileError`) rather than one giant application-wide error enum; include the data callers need for display or recovery as struct-variant fields.
- Mark a public error enum `#[non_exhaustive]` so new variants can be added later without a breaking change for downstream `match` expressions.
- For a single error type with one wrapped cause, a struct with a `#[source]` field is often simpler than a one-variant enum.

## References
- [err-thiserror-lib](err-thiserror-lib.md)
- [err-anyhow-app](err-anyhow-app.md)
