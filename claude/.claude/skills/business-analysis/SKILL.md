---
name: business-analysis
description: >-
  Produce business/impact analysis and Acceptance Criteria for a Jira ticket.
  Anchors on PR diff (post-fix) or HEAD mechanism (pre-fix). Use for impact analysis,
  bug exposure, or AC generation. Can post to Jira.
---

# Business Analysis & Acceptance Criteria

Generate business impact, technical AC, and tester BDD blocks grounded in *real code*, never just ticket prose. Applies `CLAUDE.md` writing rules.

**Modes:**
- **Post-fix**: PR exists. Anchor on diff.
- **Pre-fix**: No PR. Anchor on trace at HEAD. *You* must trace the defect.

**Refuse if:**
- PR exists but doesn't implement the ticket (drop to pre-fix or refuse).
- Trace fails (ask user for repro/logs instead of guessing).

## Workflow

### 1. Gather & 2. Trace (Pre-fix) / Read (Post-fix)
- **Post-fix**: Read core changed files in diff. Identify hot paths, blast radius, test-only changes.
- **Pre-fix**: Trace defect from symptom. Find reachability (flag defaults, auth paths) and compensating controls. (See `reference.md` commands).
- **CHECKPOINT (Pre-fix only)**: Stop and confirm the candidate mechanism (file:line) with the user *before* generating analysis. Do not skip unless user provided mechanism.

### 3. Business / Impact Analysis
- **Format**: Max 150 words. No section headers. First sentence = verdict (who is affected, what to do).
- **Content**: Risk (probability + consequence). Pre-fix needs current vs future exposure, plus Severity/Priority recommendations. Post-fix needs blast radius.
- **Drafting**: Default to drafting in chat. Ask before posting to Jira.

### 4. Criteria (Two Fields)
- **Technical AC** (`customfield_12100`): ≤6 checklist bullets. Code-verifiable assertions for engineering. Pre-fix AC must currently fail.
- **Test Ideas / BDD** (`customfield_16317`): 1 Feature, few Scenarios, plus tester note on observability limits.
- **Jira Bug Exception**: The Bug screen lacks `customfield_16317`. For Bugs, append BDD to `customfield_12100` under `### Business / Tester (BDD)`.
