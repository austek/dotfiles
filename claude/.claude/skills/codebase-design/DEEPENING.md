# Deepening Modules

How to safely deepen shallow clusters based on dependency categories. Assumes [SKILL.md](SKILL.md) vocabulary.

## Dependency Categories & Seams
1. **In-process** (Pure logic/memory): Always deepenable. Merge and test via new interface. No adapter needed.
2. **Local-substitutable** (e.g., PGLite, in-memory FS): Deepenable. Test via stand-in. Internal seam only; no port at external interface.
3. **Remote but owned** (Internal APIs/Services): Define a **port** at the seam. Deep module owns logic. Prod uses HTTP/gRPC adapter; tests use in-memory adapter.
4. **True external** (3rd-party/Stripe): Deep module takes external dependency as injected port. Tests provide mock adapter.

## Testing Strategy (Replace, Don't Layer)
- **Delete** old unit tests on shallow modules once deepened interface tests exist.
- **Interface is the test surface**: Assert observable outcomes via the interface, not internal state.
- **Resilience**: Tests describe behavior, not implementation. They must survive internal refactors.
