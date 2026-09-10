---
description: Run an end-to-end repository health, quality gate, architecture, and standards audit
allowed-tools: Bash, Glob, Read, Grep
---

Conduct a comprehensive repository audit evaluating technical debt, quantitative metrics, custom engineering standards, architectural integrity, and release readiness.

---

### Step 1: Stack Detection & Custom Standards Ingestion
1. Detect the repository runtime and build ecosystem:
   - **JVM**: `pom.xml`, `build.gradle`, `build.gradle.kts`, `gradlew`
   - **Scala**: `build.sbt`, `.scala` source trees, Mill / Scala CLI configs
   - **Python**: `pyproject.toml`, `setup.cfg`, `requirements.txt`, `Pipfile`
   - **Rust**: `Cargo.toml`, `Cargo.lock`
   - **C**: `Makefile`, `CMakeLists.txt`, `configure.ac`/`configure`, `.c`/`.h` source trees
2. Locate and load my custom standard definitions for the detected language(s):
   - Check local path: `.claude/commands/{jvm,scala,python,rust,c}.md`
   - Check global path: `~/.claude/commands/{jvm,scala,python,rust,c}.md`
   - Check skills directory: `.claude/skills/{jvm,scala,python,rust,c}/SKILL.md` (or `~/.claude/skills/...`)
   - For Python specifically, also load `~/.claude/skills/python-coding-standards/SKILL.md`, `~/.claude/skills/python-testing/SKILL.md`, and `~/.claude/skills/python-tooling/SKILL.md` (each pulls in its own `rules/*.md`) — these carry the detailed rule sets to audit against, not the generic `/python` persona command.
3. Read and incorporate all rules, conventions, and architectural constraints defined in those files as mandatory audit criteria.

---

### Step 2: Codebase Inventory & Modernization Assessment
Run the analysis patterns of `code-modernization:modernize-assess`:
- Map project inventory: module breakdown, line counts, dependency footprint.
- Identify legacy patterns, deprecated API usage, and structural complexity hotspots.
- Flag high cyclomatic complexity and deeply nested logic paths.

---

### Step 3: Quantitative Metrics & Quality Gates
1. **SonarQube Integration**:
   - If SonarQube is configured/connected, inspect:
     - `sonarqube:sonar-quality-gate` (pass/fail status)
     - `sonarqube:sonar-coverage` (line/branch coverage percentages)
     - `sonarqube:sonar-list-issues` (bugs, vulnerabilities, code smells)
     - `sonarqube:sonar-duplication` (duplicate code blocks)
     - `sonarqube:sonar-dependency-risks` (CVEs / transitive vulnerabilities)
2. **Local Build Tooling Fallback** (if SonarQube is not configured):
   - **JVM / Scala**: Run `./gradlew check jacocoTestReport` / `mvn verify` / `sbt coverage test coverageReport` via Bash.
   - **Python**: Run `pytest --cov --cov-report=term-missing` or inspect existing coverage artifacts.
   - **Rust**: Run `cargo test`, `cargo clippy --all-targets -- -D warnings`, and `cargo audit`.
   - **C**: Run the project's own test target (`make test`/`make check`, or the CMake/CTest equivalent). Separately rebuild and re-run it with `-fsanitize=address,undefined -fno-omit-frame-pointer` (add `-Werror` too if that doesn't immediately drown in pre-existing warnings) to surface memory-safety and undefined-behavior bugs a plain build won't catch. If `cppcheck` or `clang-tidy` is installed, run it for static analysis. If a coverage target exists (`gcov`/`lcov`/`gcovr`), run it; otherwise note coverage as unmeasured rather than guessing. If a fuzz target exists (libFuzzer/AFL harness), run it bounded (e.g. `-max_total_time=120`) as a smoke test.
   - Inspect build outputs and extract coverage figures and failing checks.

---

### Step 4: Architectural Review & Stack Standards Audit
1. **Custom Standards Enforcement**:
   - Strictly evaluate the codebase against the custom rules ingested in Step 1 (`/jvm`, `/scala`, `/python`, `/rust`, `/c`).
   - Flag every non-conforming pattern, naming mismatch, or forbidden pattern as explicit technical debt.
2. **Domain Boundaries & Layering**:
   - For Python: Run the evaluation patterns of `python-clean-architecture:review-architecture` (separation of domain, use cases, interfaces, and infrastructure).
   - For JVM / Scala: Inspect package boundaries, JPMS / OSGi modularity, API visibility (`api` vs `implementation`), and cyclic dependencies.
   - For Rust: Inspect crate/module hierarchy, trait boundaries, and error propagation (`Result`/`Option` ergonomics).
   - For C: Inspect header/module boundaries (what's exposed via public headers vs. kept `static`), build-flag portability (`-ansi`/`-std=`, platform `#ifdef`s), and API contract clarity (ownership of returned pointers, who calls `free`).
3. **Resource & Robustness Checks**:
   - Verify safe concurrency, memory/resource leak prevention (e.g., proper closing of streams, file handles, connections), and thread-safety invariants.
   - For C specifically: check every `malloc`/`calloc`/`realloc` has a matching `free` on all paths (including early returns and error paths), that every arithmetic operation on a buffer index or size is overflow-checked before use, and that signed integer overflow, left-shift of negative values, and out-of-bounds array/pointer access (the undefined-behavior classes ASan/UBSan catch, not just crashes a debugger would show) are treated as bugs even when a plain build doesn't visibly misbehave.

---

### Step 5: Logic, Edge Cases & PR-Level Scrutiny
Run `/code-review max` on the current branch/diff (fully local, no cloud dispatch, no billing — do not use `/code-review ultra`, which launches a separate paid cloud job I have to trigger and approve myself):
- Inspect recent commits or active branch diffs for subtle logic bugs, unhandled branch paths, off-by-one errors, or data races.
- Identify over-engineered sections that can be simplified without breaking API contracts.

---

### Output Deliverable
Generate a structured, markdown audit report following this exact layout:

# Repository Health & Quality Audit Report

## 1. Executive Summary & Quality Gate
- **Overall Status**: `PASSED` | `WARNING` | `FAILED`
- **Detected Stack**: [e.g., JVM (Kotlin/Java) + Gradle Convention Plugins]
- **Applied Custom Standards**: [e.g., loaded from `~/.claude/commands/jvm.md`]

## 2. Quantitative Metrics Matrix
| Metric | Current Value | Standard / Threshold | Status |
| :--- | :--- | :--- | :--- |
| **Test Coverage (Line / Branch)** | | | |
| **Code Duplication** | | | |
| **Bugs / Blocker Issues** | | | |
| **Security Vulnerabilities (SAST/Deps)**| | | |
| **Linter / Compiler Warnings** | | | |

## 3. Custom Standards & Architectural Compliance
- **Custom Standards Deviations**: [Specific violations of rules from `/jvm`, `/scala`, `/python`, `/rust`, or `/c`]
- **Architectural & Layering Debt**: [Boundary leaks, cyclic couplings, improper encapsulation]
- **Complexity Hotspots**: [High cyclomatic complexity / legacy areas identified in modernization assessment]

## 4. Correctness, Robustness & Edge-Case Findings
- Itemized findings on error handling, concurrency, resource management, and logic flaws.

## 5. Prioritized Remediation Roadmap
1. `[P0 - Blocker]` Critical bugs, broken quality gates, or security vulnerabilities.
2. `[P1 - High]` Custom standard violations and core architectural misalignments.
3. `[P2 - Medium]` Test coverage gaps and modernization/refactoring debt.
4. `[P3 - Low]` Documentation drift, minor duplication, or styling polish.
