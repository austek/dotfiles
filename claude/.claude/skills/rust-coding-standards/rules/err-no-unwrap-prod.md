---
title: Avoid unwrap() in Production Code
impact: HIGH
impactDescription: Prevents context-free crashes from reaching production
tags: [error-handling, unwrap, panics, production]
---

# Avoid unwrap() in Production Code [HIGH]

## Description
`unwrap()` panics on `None` or `Err` with no context about what went wrong or where. In production, that produces a cryptic crash message ("called `Option::unwrap()` on a `None` value") with no indication of which operation failed or why. Propagate the error with `?`, use `expect()` with a message that explains the invariant, or handle the failure explicitly — reserve bare `unwrap()` for tests and throwaway prototypes.

## Bad Example
```rust
fn process_request(req: Request) -> Response {
    let user_id = req.headers.get("X-User-Id").unwrap(); // Why did it fail?
    let user = database.find_user(user_id).unwrap();     // Which operation?
    let data = user.preferences.get("theme").unwrap();   // No context
    Response::new(data)
}
// Crash message: "called `Option::unwrap()` on a `None` value" - where? why? no idea.
```

## Good Example
```rust
// Propagate with ?
fn process_request(req: Request) -> Result<Response, AppError> {
    let user_id = req.headers.get("X-User-Id")
        .ok_or(AppError::MissingHeader("X-User-Id"))?;
    let user = database.find_user(user_id)?;
    let data = user.preferences.get("theme")
        .ok_or(AppError::MissingPreference("theme"))?;
    Ok(Response::new(data))
}

// Or provide a sensible default when one exists
fn get_theme(user: &User) -> &str {
    user.preferences.get("theme").unwrap_or(&"default")
}
```

## Notes
- Match the failure to its handling: propagate with `?` when the caller can decide; `unwrap_or()`/`unwrap_or_default()` when a sensible default exists; `unwrap_or_else(|| ...)` when the default needs computing; `expect("explanation")` only for genuine internal invariants.
- `clippy::unwrap_used` (and the stricter `clippy::expect_used`) as workspace lints catch stray `unwrap()`/`expect()` calls in CI; allow them locally with a comment explaining why the call site is actually safe.
- `expect()` is strictly better than `unwrap()` when a panic is truly warranted, since it at least carries a message — but the underlying issue (not propagating a recoverable error) is the same for both.

## References
- [err-result-over-panic](err-result-over-panic.md)
- [err-expect-bugs-only](err-expect-bugs-only.md)
