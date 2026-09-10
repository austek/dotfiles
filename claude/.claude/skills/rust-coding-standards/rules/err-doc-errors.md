---
title: Document Error Conditions With an Errors Section
impact: LOW
impactDescription: Callers learn failure modes from docs instead of reading source
tags: [error-handling, documentation, api-design]
---

# Document Error Conditions With an Errors Section [LOW]

## Description
Callers of a fallible function need to know what can go wrong and under what conditions. The `# Errors` doc-comment section is the standard Rust convention for describing when a function returns `Err`, and `clippy::missing_errors_doc` can enforce it. Without it, callers must read the implementation to learn what to handle — documentation that's easy to skip and quick to go stale is still better than none, but a written contract is what makes the API self-explanatory.

## Bad Example
```rust
/// Loads a configuration from the specified path.
pub fn load_config(path: &Path) -> Result<Config, ConfigError> {
    // No documentation of error conditions
    // Caller must read source code to understand what can fail
}
```

## Good Example
```rust
/// Loads a configuration from the specified path.
///
/// # Errors
///
/// Returns an error if:
/// - The file at `path` does not exist or cannot be read
/// - The file contents are not valid TOML
/// - Required configuration keys are missing
///
/// # Examples
///
/// ```
/// # use mylib::{load_config, ConfigError};
/// # fn main() -> Result<(), ConfigError> {
/// let config = load_config("app.toml")?;
/// # Ok(())
/// # }
/// ```
pub fn load_config(path: &Path) -> Result<Config, ConfigError> {
    // ...
}
```

## Notes
- Three acceptable styles, pick whichever fits the function: a bullet list of conditions for multiple independent causes, `Returns [\`Error::Variant\`] if ...` statements that map directly to enum variants, or prose for a single complex condition.
- Link to specific variants with intra-doc links (`` [`ParseError::Empty`] ``) so readers can jump straight to the variant's own documentation.
- A function that can both panic and return `Err` needs both a `# Errors` and a `# Panics` section — they document different failure classes and callers need to know both.

## References
- [doc-examples-section](doc-examples-section.md)
- [err-thiserror-lib](err-thiserror-lib.md)
