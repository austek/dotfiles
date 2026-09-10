---
title: Use Zero-Copy Patterns With Slices and Bytes
impact: HIGH
impactDescription: Removes copies from parsing and data-transfer hot paths
tags: [memory, zero-copy, slices, parsing]
---

# Use Zero-Copy Patterns With Slices and Bytes [HIGH]

## Description
Zero-copy means operating on data through references into an existing buffer instead of allocating new memory and copying bytes into it. Parsers that return `&str`/`&[u8]` slices into the original input, instead of `.to_string()`/`.to_vec()`-ing each field, avoid an allocation per field and let the compiler prove the borrow stays valid. This matters most for large inputs or high-throughput code — network packet parsing, log-line splitting, anywhere data is read once and mostly forwarded or inspected rather than mutated.

## Bad Example
```rust
// Copies every line into a new String
fn get_lines(data: &str) -> Vec<String> {
    data.lines().map(|line| line.to_string()).collect()  // Allocates per line
}

// Copies the buffer three times: header, body, and the final concat
fn process_packet(buffer: &[u8]) -> Vec<u8> {
    let header = buffer[0..16].to_vec();
    let body = buffer[16..].to_vec();
    [header, body].concat()
}
```

## Good Example
```rust
// Zero-copy: returns references into the original data
fn get_lines(data: &str) -> Vec<&str> {
    data.lines().collect()  // Just pointers and lengths
}

// Zero-copy slicing: no allocation, no copy
fn process_packet(buffer: &[u8]) -> (&[u8], &[u8]) {
    (&buffer[0..16], &buffer[16..])
}

// Zero-copy parsing: fields reference the input's lifetime
struct Parsed<'a> {
    name: &'a str,
    value: &'a str,
}

fn parse(input: &str) -> Parsed<'_> {
    let (name, value) = input.split_once('=').unwrap();
    Parsed { name, value }
}
```

## Notes
- `bytes::Bytes` gives zero-copy slicing with reference counting for owned byte buffers — `.slice(range)` shares the underlying allocation instead of copying, freeing it only once every slice referencing it is dropped.
- `Cow<'static, str>` is the standard escape hatch for "usually zero-copy, occasionally must own": return `Cow::Borrowed` for known static values (HTTP method names, fixed keywords) and `Cow::Owned` only for the rare dynamic case.
- Zero-copy has a real limit: it doesn't apply when the data must be mutated in place (uppercase conversion needs a new buffer), must outlive its source (storing a parsed field after the source string is dropped), or must cross a thread boundary without `Arc`/`Bytes` sharing — all three genuinely require a copy.
- `memchr` provides SIMD-accelerated byte search (`memchr`, `memchr_iter`) that finds delimiters without allocating, a natural complement to zero-copy slicing when writing your own parser.
- A struct holding borrowed fields (`Parsed<'a>`) ties its lifetime to the source — that's the mechanism, not a limitation: the borrow checker enforces the source outlives every zero-copy view into it.

## References
- [own-cow-conditional](own-cow-conditional.md)
- [own-borrow-over-clone](own-borrow-over-clone.md)
- [mem-arena-allocator](mem-arena-allocator.md)
