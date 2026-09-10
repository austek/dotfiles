---
name: verifying-code-claims
description: >-
  Verify code claims before approving diffs, PRs, or refactors (e.g., mechanical cleanup, renames, type swaps, version bumps, security controls, caches, collections, suppressions).
---

# Verifying Code Claims

Code self-descriptions (names, types, javadocs, PR prose) are claims. Any can be false. Do not accept self-descriptions; read the code to verify terminal conditions. Prose/code disagreement is a finding.

## Required Output Format
For every claim the change depends on, your review MUST output:
`<claim> — holds because <file:line>, where <the terminal condition>`

- **Terminal condition**: The actual condition (e.g., `if (subject.isAuthenticated())`), not just a call site (`calls logout()`).
- If unverified, output `UNVERIFIED` and state what you need to read. (Unverified claims are findings).

## Output Rules (Strict)
- **No Positive Summary**: Open directly with findings, ranked most severe first. Do not assess author care or change tidiness.
- **Voice**: Active voice only. Concrete specifics (`File.java:NNN`). 
- **Banned Words**: delve, robust, seamless, comprehensive, holistic, leverage, utilize, ensure, streamline, innovative, granular. No summary paragraphs.

## Worked Example (Session Fixation)
- *Wrong (Accepting description)*: `SessionResource.login` calls `logout(request)`. Rotation preserved. APPROVE.
- *Right (Terminal trace)*: `UserAuthenticationServiceImpl.logout()` (`:114`) checks `if (subject.isAuthenticated())`. A planted pre-auth session is unauthenticated -> no-op -> `request.getSession()` returns same ID. Session fixation. REQUEST CHANGES.

## Claims Made by Types and Names
| Change / Type | Actual Behavior / Gotcha |
|---|---|
| `Arrays.asList` → `List.of` | `contains`/`indexOf`/`remove(null)` throws NPE. Null elements rejected. `set()` removed. |
| `HashMap` → `ConcurrentHashMap` | Rejects null keys and values (NPE on `put`/`get`). |
| `Map.of` / `Set.of` | Duplicates throw `ExceptionInInitializerError`. Iteration order is salted/unspecified. |
| `Collections.unmodifiableX(c)` | A **view**, not a copy (`c` still mutates). |
| `EnumSet/Map` → `Set/Map` | Loses `contains(null) == false`. Binary break for precompiled callers. |
| `TreeMap/Set` | Null key/element throws under natural ordering. |
| `stream.toList()` | Unmodifiable (unlike `collect(toList())`). |
| `Collectors.toMap` | NPEs on null values. Throws on duplicate keys. |
| `@Qualifier("name")` on `Map<K,V>` | If bean missing, Spring injects empty map silently. Use `ConcurrentMap`/concrete to fail loudly. |
| `@Import`ed bean | Named by FQCN, not simple name (breaks by-name injection). |
| `static` → `instance` field | Changes the scope a `synchronized` method actually guards. |
| BOM import in root | `io.spring.dependency-management` does **not** inherit. Subprojects keep old versions. |
| `implementation(platform(x))` | In a `java-library`, exports the constraint to all downstream consumers. |

## High-Risk Claims (Never Self-Evident)
- **Suppression Entries**: Added API-compat, ArchUnit, Sonar, or `@SuppressWarnings` means a guard fired. Report what it hides and why it's acceptable.
- **Removed Security Controls**: Deleting a check/filter to fix an error means the control was working. Name what it defended. Fix idempotently instead of neutralizing.

## Common Mistakes
- **Predicting instead of reading**: "This would fail at startup" is a claim. Read the code or write a probe (silent-empty vs loud-throw look identical in diffs).
- **Trusting green builds**: Mocked collaborators and context-start tests pass over these defects.
- **Auditing fixed guards**: If diff adds one null check, audit the *other* call sites, not the fixed one.
- **Scoring reach without scoping**: Finding a change landed in 1 of 3 places is half the work; evaluating if that is correct is the rest.
