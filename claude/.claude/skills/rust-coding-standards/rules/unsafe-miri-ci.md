---
title: Run cargo miri test in CI for Every Unsafe-Containing Crate
impact: HIGH
impactDescription: Dynamically catches UB that static review and normal tests miss
tags: [unsafe, miri, ci, undefined-behavior]
---

# Run cargo miri test in CI for Every Unsafe-Containing Crate [HIGH]

## Description
Miri is the only tool that *dynamically* detects undefined behavior in Rust programs at test execution time — out-of-bounds accesses, use-after-free, reads of uninitialized memory, invalid pointer provenance, data races in unsafe multithreaded code, and violations of the Stacked Borrows / Tree Borrows aliasing models. Static analysis and code review can miss UB that only manifests under a specific memory layout or interleaving; running the existing test suite under Miri catches it unconditionally, without writing a single new test. The standard library, tokio, and serde all gate merges that touch unsafe code on a passing Miri run.

## Bad Example
```yaml
# CI that tests but never runs Miri — unsafe code ships unverified,
# with no dynamic UB detection at all.
- name: Test
  run: cargo test --all-features
```

## Good Example
```yaml
# .github/workflows/miri.yml
name: Miri

on: [push, pull_request]

jobs:
  miri:
    name: Miri (nightly)
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Install nightly toolchain with Miri
        run: |
          rustup toolchain install nightly --component miri
          rustup override set nightly
          cargo miri setup

      - name: Run Miri
        env:
          MIRIFLAGS: "-Zmiri-strict-provenance"
        run: cargo miri test --all-features
```

## Notes
- Miri requires a nightly toolchain — pin a specific nightly date in `rust-toolchain.toml` if CI needs reproducible results across runs.
- Miri interprets rather than compiles, so test suites run 100-1000x slower than a normal `cargo test`; run it on a reduced test subset or a separate, slower CI job if the full suite is prohibitive.
- `MIRIFLAGS=-Zmiri-strict-provenance` catches pointer casts that violate the provenance model; add `-Zmiri-tree-borrows` to opt into the newer, less restrictive Tree Borrows aliasing model instead of the default Stacked Borrows.
- Run `cargo miri setup` once per CI cache key to pre-build the Miri sysroot, so the first real test run isn't paying a cold-start cost every time.
- Crates with zero `unsafe` code gain nothing from Miri; skip it there. Generated code or proc-macro output you don't control is better audited at the generator, not chased through Miri output.

## References
- [unsafe-maybeuninit](unsafe-maybeuninit.md)
- [unsafe-safety-comment](unsafe-safety-comment.md)
