---
name: codebase-design
description: >-
  Vocabulary and principles for designing deep modules. Use to design interfaces, find deepening opportunities, place seams, or improve testability.
---

# Codebase Design: Deep Modules

## Glossary (Strict Usage)
- **Module**: Interface + implementation. (Avoid: unit, component, service).
- **Interface**: Everything a caller must know (signatures, invariants, errors, performance). (Avoid: API).
- **Implementation**: The body of code inside a module.
- **Depth**: Leverage at the interface. (Deep = small interface + large implementation. Shallow = large interface + thin implementation).
- **Seam**: Where a module's interface lives; where behavior can be altered without editing. (Avoid: boundary).
- **Adapter**: Concrete implementation filling a slot at a seam.
- **Leverage**: Caller benefit (more capability per learned interface unit).
- **Locality**: Maintainer benefit (change/bugs concentrate in one place).

## Principles
- **Depth is interface-relative**: Modules can have internal seams/parts not exposed via the external interface.
- **Deletion test**: If deleting a module merely moves complexity to callers, it was a pass-through (shallow).
- **Interface = test surface**: Callers and tests cross the same seam. Do not test past the interface.
- **Seam Rule**: ≥2 adapters required to justify a seam (e.g., prod + test). 1 adapter = mere indirection.

## Testability Design
1. **Inject dependencies**: Accept them, do not instantiate them.
2. **Return results**: Avoid side effects (mutating inputs).
3. **Minimize surface**: Fewer methods/params = simpler test setup.

## Going Deeper
- Deepening a cluster given its dependencies → [DEEPENING.md](DEEPENING.md)
- Exploring alternative interfaces via parallel sub-agents → [DESIGN-IT-TWICE.md](DESIGN-IT-TWICE.md)
