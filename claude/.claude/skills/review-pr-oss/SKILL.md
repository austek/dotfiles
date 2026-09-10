---
name: review-pr-oss
description: >-
  Review a PR on a personal or open-source GitHub repo. No CODEOWNERS/team scoping — reviews the full
  diff, detects languages, applies the repo's own CONTRIBUTING.md/CLAUDE.md rules + language persona
  skills, checks DCO/CLA sign-off, and delegates to pr-review-toolkit:review-pr.
---

# Reviewing a PR on a Personal/OSS Repo

Default posture: maintainer reviewing an external contribution (or a fellow contributor's PR on a repo
you don't own) — no internal CODEOWNERS scope, no internal-org ticketing/PR conventions apply.

## 1. Resolve PR & Materialize Diff
1. Identify PR via arg (`/review-pr-oss 456`, URL, branch) or current branch
   (`gh pr view --json number,url,headRefName,baseRefName`).
2. Materialize in an isolated worktree:
   ```bash
   git fetch origin pull/<number>/head:review-pr-<number>
   git worktree add /tmp/review-pr-<number> review-pr-<number>
   ```
3. Run git commands inside `/tmp/review-pr-<number>`. Changed files via
   `git diff <base>...<head> --name-only`, full diff via `gh pr diff <number>`.
4. Clean up worktree (`git worktree remove`) when finished.

## 2. Full-Diff Scope (No CODEOWNERS Gate)
Review the entire diff — an OSS repo's CODEOWNERS (if any) marks notification routing, not review
boundaries. Note in the report if a CODEOWNERS file exists and who else it flags for this diff.

## 3. Gather Guidance
Combine, in order of specificity:
- **Repo's own rules**: `CONTRIBUTING.md`, `CLAUDE.md`/`AGENTS.md`, `.github/*` style docs — these are
  authoritative over any personal default.
- **Language persona skills**: `jvm`, `python`, `rust`, `scala` for the detected extensions.
- **Sign-off/CLA requirement**: check `CONTRIBUTING.md` and workflow names for DCO/CLA bots; flag a
  missing `Signed-off-by:` trailer as a blocking finding if the repo requires it.

## 4. Delegate Review
Execute `pr-review-toolkit:review-pr` inside the worktree directory against the full
`<base>...<head>` diff, passing the combined guidance from §3 as additional criteria. No external-team
persona override — review as a knowledgeable maintainer/contributor.

## 5. Deduplicate Against Existing Comments
```bash
gh api repos/<owner>/<repo>/pulls/<number>/comments
gh api repos/<owner>/<repo>/pulls/<number>/reviews
```
Drop findings matching an existing comment on the same file/line/hunk; keep distinct new issues on the
same line.

## 6. Prepare Findings & Get Confirmation Before Posting
Never call the GitHub API to post anything until the user has explicitly approved the exact content.

1. Get the head commit SHA: `gh pr view <number> --json headRefOid -q .headRefOid`.
2. For each finding, resolve `path`, `line` (from the file in the worktree, not hand-counted diff
   offsets), and `side: "RIGHT"` (`"LEFT"` only for a finding about deleted code).
3. Never post **Strengths**/positive-only observations as comments. Only draft actionable findings
   (issue/suggestion/nit/question).
4. Build the exact `review.json` payload. No overview/summary top-level comment — inline findings only,
   plus a separate draft for genuine cross-cutting findings that can't anchor to a line:
   ```json
   {
     "commit_id": "<headRefOid>",
     "event": "COMMENT",
     "comments": [
       {"path": "...", "line": 123, "side": "RIGHT", "body": "**label**: point [fix]"}
     ]
   }
   ```
5. Show the user the full draft before posting: every inline comment rendered as
   `path:line — **label**: text`, plus any top-level-only comments. This is the actual content to be
   posted, not a paraphrase.
6. Stop and wait for approval. Anything other than a clear go-ahead is a revision request — edit and
   re-show the draft.

Findings Format:
- Group by severity: Critical / Important / Suggestions.
- 1–2 sentences per finding (`**label**: point [fix]`) — no repeated `path:line` inside comment bodies.
- Labels: **issue**, **suggestion**, **nit**, **question**.
- No raw tool transcripts, long code blocks, or section headers like "Impact:".

## 7. Post Findings as Inline PR Comments
Only after approval:
1. Batch into one review call: `gh api repos/<owner>/<repo>/pulls/<number>/reviews --input review.json`.
   If the API rejects an empty `body` for `event: "COMMENT"`, drop the batch and post each inline
   finding individually via `gh api repos/<owner>/<repo>/pulls/<number>/comments` instead.
2. Post any approved top-level-only findings via `gh pr comment`.

## 8. Report to User
Short chat summary: counts by severity, link to the review (`html_url`), sign-off/CLA status, and
number of dropped duplicate findings.
