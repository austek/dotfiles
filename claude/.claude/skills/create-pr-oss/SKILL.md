---
name: create-pr-oss
description: >-
  Open a pull request on a personal or open-source GitHub repo: fork/upstream detection, repo's own
  contribution conventions (CONTRIBUTING.md, PR template, DCO/CLA sign-off), branch naming, and check
  monitoring. Use for "create/open a PR" or "push & open PR" on a repo outside your internal org.
---

# Opening a PR on a Personal/OSS Repo

Default posture: no org-wide template or Jira key applies here — the target repo's own conventions are
authoritative. Never impose your internal org's `<JIRA-KEY>: subject` or PR template on an OSS repo.

## 1. Word Budget & Voice (Soft Defaults, Repo Wins)
- Keep active voice, no throat-clearing ("This PR..."), no summary paragraphs — that's a writing-quality
  baseline, not a hard cap.
- Word caps and section structure come from the repo's own `.github/pull_request_template.md` /
  `CONTRIBUTING.md` if present. Follow those over any personal default.
- **Safety**: Never commit, push, fork, open, or merge a PR without explicit user instruction.

## 2. Comment Pass
Before writing the PR description, check whether the diff touches comments:
```bash
git diff <base>...HEAD -U0 -- . | grep -qE '^\+.*(//|#[^!]|/\*|\*/)'
```
If it does, invoke the `prune-comments` skill scoped to this branch first.

## 3. Fork/Upstream Detection
Most OSS contributions need a fork — you rarely have direct push access:
```bash
gh repo view <owner>/<repo> --json viewerPermission -q .viewerPermission
```
- `WRITE`/`ADMIN`/`MAINTAIN`: push a branch directly, same as an internal repo.
- `READ`/`NONE`: fork first (`gh repo fork <owner>/<repo> --clone=false`), push to
  `<you>/<repo>`, then `gh pr create --repo <owner>/<repo> --head <you>:<branch>`.
- Check for an existing fork before creating a new one: `gh repo view <you>/<repo>` (404 = no fork yet).

## 4. Repo Convention Detection
Run before writing anything:
```bash
# Commit/branch convention from recent history
gh api "repos/<owner>/<repo>/commits?per_page=8" --jq '.[].commit.message | split("\n")[0]'

# Contribution guide (sign-off requirement, style guide, test requirements)
gh api repos/<owner>/<repo>/contents/CONTRIBUTING.md --jq .content 2>/dev/null | base64 -d

# PR template (repo-specific, never fall back to an org template here)
gh api repos/<owner>/<repo>/contents/.github/pull_request_template.md --jq .content 2>/dev/null | base64 -d

# DCO/CLA bot present?
gh api repos/<owner>/<repo>/contents/.github/workflows --jq '.[].name' 2>/dev/null | grep -iE "dco|cla"
```
If `CONTRIBUTING.md` requires sign-off, commit with `git commit -s` (adds `Signed-off-by:`) — check
before the first commit, not after CI flags it.

## 5. Mechanics That Bite
- **Force Push**: Use `--force-with-lease=<ref>:<sha>` even on your own fork branch.
- **Existing PRs**: Check `gh pr list --repo <owner>/<repo> --head "<you>:<branch>"` before creating.
- **Upstream drift**: Rebase onto current upstream default branch before opening — OSS maintainers expect
  a clean rebase, not a merge commit, unless the repo says otherwise.
- **Zsh & Shell**: Quote glob args (`--include="*.yaml"`). Use plain `grep -rn` and `find`.

## 6. Check Monitoring
Same polling pattern as internal repos — run under bash, not zsh:
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
OSS CI often includes a CLA/DCO check bucket — treat it like any other required check, don't skip it.

## 7. Pre-Completion Checklist
- [ ] Comment pass run if the diff touched comments (§2).
- [ ] PR targets the correct upstream repo/branch, not your fork's default branch.
- [ ] Sign-off applied if `CONTRIBUTING.md` requires it.
- [ ] Description follows the repo's own template, not your internal org's default.
