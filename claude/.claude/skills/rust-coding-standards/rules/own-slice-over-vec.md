---
title: Accept Slices Instead of Vec and String References
impact: MEDIUM
impactDescription: Widens callable inputs to any slice/string-like source
tags: [ownership, api-design, slices, flexibility]
---

# Accept Slices Instead of Vec and String References [MEDIUM]

## Description
Accepting `&[T]` instead of `&Vec<T>` makes a function more flexible — it can take slices from arrays, vectors, or any other source, since `&Vec<T>` coerces to `&[T]` automatically but not the other way around. The same logic applies to `&str` versus `&String`: `&str` accepts string slices from a `String`, a `&'static str` literal, or a substring, while `&String` accepts only an actual `String`.

## Bad Example
```rust
// Overly restrictive - only accepts &Vec
fn sum(numbers: &Vec<i32>) -> i32 {
    numbers.iter().sum()
}

// Overly restrictive - only accepts &String
fn greet(name: &String) {
    println!("Hello, {}", name);
}

let arr = [1, 2, 3];
// sum(&arr);  // ERROR: expected &Vec<i32>
let literal = "world";
// greet(&literal);  // ERROR: expected &String
```

## Good Example
```rust
// Flexible - accepts any slice-like thing
fn sum(numbers: &[i32]) -> i32 {
    numbers.iter().sum()
}

// Flexible - accepts any string-like thing
fn greet(name: &str) {
    println!("Hello, {}", name);
}

let vec = vec![1, 2, 3];
let arr = [4, 5, 6];
sum(&vec);  // Vec coerces to slice
sum(&arr);  // Array coerces to slice

let string = String::from("Alice");
greet(&string);  // String coerces to &str
greet("Bob");     // &str works directly
```

## Notes
- The same deref-coercion principle extends further: prefer `&Path` over `&PathBuf`, and `impl AsRef<Path>` when a function should accept anything path-like (`&str`, `&String`, `&Path`, `&PathBuf`) without the caller needing to convert first.
- Coercion is one-directional and automatic: `Vec<T> -> &[T]`, `String -> &str`, `Box<T> -> &T`, `Arc<T> -> &T` via `Deref`; a function that demands the owned/boxed type upfront forfeits that flexibility for callers.
- Accept an owned type only when the function actually needs to store the value; if it just needs a hint of ownership from the caller, `impl Into<String>` lets the caller pass either an owned `String` or a `&str` literal without an extra explicit `.to_string()`.

## References
- [own-borrow-over-clone](own-borrow-over-clone.md)
- [own-cow-conditional](own-cow-conditional.md)
