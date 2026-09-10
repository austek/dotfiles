---
name: to-questionnaire
description: >-
  Turn an unresolved decision into a Markdown questionnaire to extract missing knowledge from a recipient async or in a meeting.
disable-model-invocation: true
---

# Questionnaire Generation

Create a Markdown questionnaire to extract missing knowledge from a recipient. **Interview the user about the *send*, not the subject.**

## Workflow
1. **Who?** Ask for the recipient's role, expertise, and relationship to the user (sets tone and context depth).
2. **What?** Ask for the specific decisions/facts the user needs back (sets the content).
3. **Write**: Draft the document to `to-questionnaire-<slug>.md` (slug derived from topic). Ensure every item from Step 2 is covered. Report the file path.

## Document Structure
Order questions most-important-first. Group under `##` themes if numerous. 

<questionnaire-template>

# <Questionnaire Title>

**Purpose:** <Why this exists — the decision it's riding on>
**From:** <User> | **To:** <Recipient> | **Usage:** <How answers will be used>

## Context
<One orienting paragraph for the recipient.>

## How to Answer
<Deadline. Note that partial answers are acceptable — "I don't know" is a valid answer and takes less effort than guessing.>

## <Theme Heading>
<Questions ordered most-important-first, one idea per question (never compound).>

### <Question>
*Why this matters: <1-line context, only if needed to prevent throwaway answers>*
>

## Anything Else?
<Catch-all for any missed context>

</questionnaire-template>