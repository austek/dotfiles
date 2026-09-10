---
title: Mark Builder Methods With #[must_use]
impact: MEDIUM
impactDescription: Turns silently-dropped configuration into a compiler warning
tags: [api-design, builder, must-use, ergonomics]
---

# Mark Builder Methods With #[must_use] [MEDIUM]

## Description
Builder methods return a modified builder rather than mutating in place. Without `#[must_use]`, calling one and ignoring the return value compiles cleanly and silently does nothing — the modified builder is dropped, and the configuration it carried is lost. This produces code that looks correct (`request.timeout(Duration::from_secs(30));`) but has no effect whatsoever, a bug class that `#[must_use]` converts into a compiler warning at the call site.

## Bad Example
```rust
struct RequestBuilder {
    url: String,
    timeout: Option<Duration>,
}

impl RequestBuilder {
    fn timeout(mut self, duration: Duration) -> Self {
        self.timeout = Some(duration);
        self
    }
}

// Bug: builder methods are ignored — no warning!
let request = RequestBuilder::new("https://api.example.com");
request.timeout(Duration::from_secs(30));  // Dropped silently
let response = request.send();             // Sends with no timeout
```

## Good Example
```rust
struct RequestBuilder {
    url: String,
    timeout: Option<Duration>,
}

impl RequestBuilder {
    #[must_use = "builder methods return a modified builder - chain or assign"]
    fn timeout(mut self, duration: Duration) -> Self {
        self.timeout = Some(duration);
        self
    }
}

// Now warns: unused return value that must be used
let request = RequestBuilder::new("https://api.example.com");
request.timeout(Duration::from_secs(30));  // Warning!

// Correct: chain methods
let response = RequestBuilder::new("https://api.example.com")
    .timeout(Duration::from_secs(30))
    .send();
```

## Notes
- Applying `#[must_use = "..."]` to the builder struct itself, not just each method, catches the case where the builder is constructed and never touched at all — combine both for full coverage.
- Write a message that tells the reader what to do, not just that something is wrong: `"builder methods return a modified builder - chain or assign"` beats a bare `#[must_use]` with no explanation.
- `clippy::return_self_not_must_use` specifically flags `-> Self` methods missing the attribute; enable it in `[lints.clippy]` so new builder methods can't forget it.
- The standard library follows this pattern already — `Result`, `Option::map`, and iterator adaptors are all `#[must_use]`, so builders that skip it are the outlier, not the norm.
- `clippy::must_use_candidate` suggests places where the attribute would help but wasn't added, useful for auditing an existing builder API.

## References
- [api-builder-pattern](api-builder-pattern.md)
- [api-must-use](api-must-use.md)
- [err-result-over-panic](err-result-over-panic.md)
