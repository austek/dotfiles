---
name: land-pr-oss
description: >-
  Shepherd your own open PR on a personal/OSS repo to mergeable: poll CI, pull failing-check logs,
  fetch reviewer feedback (inline threads + review verdicts), draft fixes, push after confirmation,
  reply to and resolve the threads that fix actually addresses. Use for "check my PR", "is my PR green",
  "address the review comments", or "land this PR".
---

# Landing Your Own PR on a Personal/OSS Repo

Default posture: you're the PR author. This skill drives the PR toward merge — it does not review someone
else's code (`review-pr-oss` for that) and does not open new PRs (`create-pr-oss` for that).

## 1. Resolve Target PR
Identify via arg (`/land-pr-oss 456`, URL) or current branch:
```bash
gh pr view --json number,url,headRefName,baseRefName,headRepositoryOwner,isCrossRepository
```
Work in the actual checkout (not a worktree) — fixes get committed and pushed from here.

## 2. CI Status
Poll checks (same pattern as `create-pr-oss` §6):
```bash
bash -s <<'EOF'
prev=""
for i in $(seq 1 20); do
  s=$(gh pr checks $N --repo <owner>/<repo> --json name,bucket 2>/dev/null) \
    || { echo "checks not available yet"; sleep 30; continue; }
  cur=$(jq -r '.[] | select(.bucket!="pending") | "\(.name): \(.bucket)"' <<<"$s" | sort -u)
  comm -13 <(printf '%s\n' "$prev") <(printf '%s\n' "$cur") | grep -v '^[[:space:]]*$' || true
  prev="$cur"
  jq -e 'length>0 and all(.bucket!="pending")' <<<"$s" >/dev/null 2>&1 && break
  sleep 30
done
EOF
```
For each failing check, pull the actual failure, not just the red X:
```bash
gh run list --repo <owner>/<repo> --branch <branch> --json databaseId,workflowName,conclusion --jq '.[] | select(.conclusion=="failure")'
gh run view <run-id> --repo <owner>/<repo> --log-failed
```

## 3. Fetch Reviewer Feedback
Inline threads with resolve state (REST doesn't expose `isResolved` — use GraphQL):
```bash
gh api graphql -f query='
query($owner:String!,$repo:String!,$number:Int!){
  repository(owner:$owner,name:$repo){
    pullRequest(number:$number){
      reviewThreads(first:100){
        nodes{ id isResolved isOutdated path line
          comments(first:50){ nodes{ id body url author{login} } } } } } } }' \
  -f owner=<owner> -f repo=<repo> -F number=<number>
```
Top-level review verdicts (approvals/change requests without an inline anchor):
```bash
gh pr view <number> --repo <owner>/<repo> --json reviews --jq '.reviews[] | {author: .author.login, state, body}'
```
Work set = unresolved, non-outdated threads + any `CHANGES_REQUESTED` review body.

## 4. Draft Fixes & Confirm Before Pushing
For each item in the work set, draft the code change. Then, before touching git:
- Show the user a summary: which CI failure or which thread each change addresses, and the diff.
- Wait for explicit go-ahead. Treat anything other than clear approval as a revision request.
- Never push, comment, or resolve anything until approved — same rule as `create-pr-oss` §1 Safety.

An ambiguous or debatable comment (reviewer disagrees on approach, asks a question with no clear
single fix) is not something to silently code around — draft a reply instead and leave the thread open
for the user to send, don't invent a resolution to make the thread count go down.

## 5. Push & Reply
After approval:
1. Commit with sign-off if the repo requires it (per `create-pr-oss` §4 detection), push to the PR branch.
2. Reply on each addressed thread (references the fixing commit):
   ```bash
   gh api repos/<owner>/<repo>/pulls/<number>/comments/<comment_id>/replies -f body="Fixed in <sha>."
   ```
3. Reply to a `CHANGES_REQUESTED` review body via `gh pr comment <number> --body "..."` if it has no
   inline anchor.

## 6. Resolve Threads
Resolve only threads whose comment was actually addressed by the pushed commit — never resolve a
thread to clear the count:
```bash
gh api graphql -f query='mutation($id:ID!){resolveReviewThread(input:{threadId:$id}){thread{isResolved}}}' -f id=<threadId>
```

## 7. Re-Loop
After pushing, CI re-runs — go back to §2. Stop when: all checks pass, no unresolved actionable threads
remain, and no drafted reply is still pending send. Report anything still open and why (debatable
comment, flaky/still-failing check, waiting on a maintainer reply) rather than declaring it landed.

## 8. Pre-Completion Checklist
- [ ] Every failing check root-caused (log pulled), not just retried blind.
- [ ] Every resolved thread was actually addressed by a pushed commit, not just marked resolved.
- [ ] Debatable/ambiguous comments left open with a drafted reply, not silently resolved.
- [ ] User approved every push before it happened.
