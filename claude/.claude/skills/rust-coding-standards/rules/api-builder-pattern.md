---
title: Use the Builder Pattern for Complex Construction
impact: HIGH
impactDescription: Replaces error-prone positional constructors with a self-documenting API
tags: [api-design, builder, construction, ergonomics]
---

# Use the Builder Pattern for Complex Construction [HIGH]

## Description
A constructor with many parameters, especially several of the same type, is error-prone — callers can't tell which positional argument means what, and swapping two `bool`s or two `Option<T>`s compiles without a hint of the mistake. The builder pattern replaces that with named, chainable methods that read like documentation at the call site, defers validation to a single `build()` step, and lets you add new optional configuration later without breaking every existing caller.

## Bad Example
```rust
// Constructor with many parameters — hard to read, easy to get wrong
let client = Client::new(
    "https://api.example.com",  // Which is which?
    30,                          // Timeout? Retries?
    true,                        // What does this mean?
    None,
    Some("auth_token"),
    false,
);
```

## Good Example
```rust
#[derive(Default)]
#[must_use = "builders do nothing unless you call build()"]
pub struct ClientBuilder {
    base_url: Option<String>,
    timeout: Option<Duration>,
    max_retries: u32,
    auth_token: Option<String>,
}

impl ClientBuilder {
    pub fn new() -> Self {
        Self::default()
    }

    /// Sets the base URL for all requests.
    pub fn base_url(mut self, url: impl Into<String>) -> Self {
        self.base_url = Some(url.into());
        self
    }

    /// Sets the request timeout. Default is 30 seconds.
    pub fn timeout(mut self, timeout: Duration) -> Self {
        self.timeout = Some(timeout);
        self
    }

    /// Builds the client with the configured options.
    pub fn build(self) -> Result<Client, BuilderError> {
        let base_url = self.base_url.ok_or(BuilderError::MissingBaseUrl)?;
        Ok(Client {
            base_url,
            timeout: self.timeout.unwrap_or(Duration::from_secs(30)),
            max_retries: self.max_retries,
            auth_token: self.auth_token,
        })
    }
}

// Usage — clear and self-documenting
let client = ClientBuilder::new()
    .base_url("https://api.example.com")
    .timeout(Duration::from_secs(10))
    .build()?;
```

## Notes
- Prefer consuming builder methods (`mut self -> Self`) over borrowing ones (`&mut self -> &mut Self`) — consuming is the ecosystem default (`reqwest::ClientBuilder`) and pairs naturally with `#[must_use]` to catch dropped configuration.
- A typestate builder — a distinct type per required-field state — can make a missing required field a compile error instead of a runtime `Result::Err`, at the cost of more type machinery; reach for it when a field's absence is a common, costly mistake.
- `build()` returning `Result<T, BuilderError>` is the right shape when required fields might be missing; return `T` directly (infallible) when every field has a sensible default and construction genuinely cannot fail.
- Derive `Default` on the builder so `Builder::default()` and `Builder::new()` both work, and mark the builder type `#[must_use]` in addition to each method, so an entirely unused builder is flagged too.
- Don't reach for a builder when a type has two or three simple, unambiguous fields — a plain constructor is clearer there, and a builder only adds ceremony.

## References
- [api-builder-must-use](api-builder-must-use.md)
- [api-typestate](api-typestate.md)
- [api-impl-into](api-impl-into.md)
