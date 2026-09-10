# Design It Twice

Parallel sub-agent pattern for exploring alternative deep module interfaces. Uses [SKILL.md](SKILL.md) vocabulary.

## Workflow

### 1. Frame Problem (User-Facing)
Write and show the user:
- Constraints the new interface must satisfy.
- Dependencies + categories (from [DEEPENING.md](DEEPENING.md)).
- Illustrative code sketch (concrete grounding, not a proposal).

Wait for user to read while sub-agents spawn.

### 2. Spawn Sub-Agents (Parallel)
Spawn ≥3 sub-agents with a technical brief (files, coupling, dependencies). Enforce domain & [SKILL.md](SKILL.md) vocabulary. Apply distinct constraints:
- **Agent 1**: Minimize interface (1-3 entry points max). Maximize leverage.
- **Agent 2**: Maximize flexibility (many use cases/extension).
- **Agent 3**: Optimize common caller (trivial default case).
- **Agent 4** (Optional): Design around ports & adapters.

**Agent Output Requirements:**
1. Interface (types, invariants, errors).
2. Usage example.
3. Hidden implementation details.
4. Dependency strategy / adapters.
5. Trade-offs (leverage vs. thinness).

### 3. Present & Compare
- Present designs sequentially.
- Compare via prose on **depth** (leverage), **locality**, and **seam placement**.
- Provide an opinionated recommendation (best design or hybrid). Do not just offer a menu.
