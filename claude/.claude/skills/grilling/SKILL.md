---
name: grilling
description: >-
  Grill the user relentlessly about a plan, decision, or idea to stress-test their thinking.
---

# Grilling

Interview the user relentlessly to achieve a shared understanding. Map the problem as a **design tree** (every decision branches into dependent decisions).

## 1. Core Mechanics
- **The Frontier**: The set of decisions whose prerequisites are already settled.
- **Rounds**: Ask the *entire* frontier in a single round. Wait for user answers before proceeding.
- **Tree Reshaping**: Settled decisions unblock dependent questions for *later* rounds. Never ask a question that depends on another open question in the same round.
- **Completion**: Done when the frontier is empty (all branches visited, nothing assumed). Do NOT act until the user explicitly confirms shared understanding.

## 2. Output Format
Number each question and provide a recommended answer. Use this exact format:

```text
❓ **Q<N>** - **<Question Title>**: <Question body, context, or multiple choices>

➡️ <Your recommended answer>
```

## 3. Fact-Finding vs. Decisions
- **Facts**: Finding facts is YOUR job. If a frontier question requires environment context (files, tools), dispatch a sub-agent to find it. Do NOT ask the user for facts you can look up yourself.
- **Non-Blocking**: Do not block the whole round on a sub-agent. Ask the rest of the frontier immediately. Only the questions downstream of the running sub-agent must wait.
- **Decisions**: Only decisions belong to the user.
