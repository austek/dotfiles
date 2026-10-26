#!/bin/bash
# Apply a baseline branch-protection ruleset to an owner's repos.
# Org-wide rulesets need GitHub Team; this is the free-plan equivalent.
#
#   github-rulesets.sh [owner]          # default owner: ZirekHQ
#   github-rulesets.sh --dry-run austek # print the calls and payloads; GETs only
#   DRY_RUN=1 github-rulesets.sh austek # same as --dry-run
#   REPOS="a b" github-rulesets.sh austek    # explicit list, skips discovery
#   INCLUDE_FORKS=1 ...                      # forks are skipped by default
#   REQUIRE_PR=1 ...                         # also require a PR (0 approvals)
#   REQUIRE_PR=0 ...                         # drop any existing PR requirement
#
# A PUT replaces the whole ruleset, so the current ruleset is fetched and only the
# managed rules are merged into it: other rules, bypass actors, conditions and an
# existing pull_request rule's parameters survive. An unset REQUIRE_PR keeps the
# repo's pull_request rule as is.

set -euo pipefail

DRY_RUN="${DRY_RUN:-0}"
positional=()
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=1 ;;
    *) positional+=("$arg") ;;
  esac
done
OWNER="${positional[0]:-ZirekHQ}"
RULESET_NAME="baseline"
REQUIRE_PR="${REQUIRE_PR:-preserve}"
INCLUDE_FORKS="${INCLUDE_FORKS:-0}"
REPOS="${REPOS:-}"

command -v gh >/dev/null || { echo "gh not found" >&2; exit 1; }

build_payload() {
  local require_pr_review="$1" existing_json="${2:-}"
  python3 -c '
import json, sys
current = json.loads(sys.argv[3]) if sys.argv[3] else {}
managed = ("deletion", "non_fast_forward", "required_linear_history")
kept = [r for r in current.get("rules", []) if r["type"] not in managed + ("pull_request",)]
old_pr = [r for r in current.get("rules", []) if r["type"] == "pull_request"]
rules = [{"type": t} for t in managed] + kept
if sys.argv[2] == "1" and old_pr:
    rules.append(old_pr[0])
elif sys.argv[2] == "1":
    rules.append({"type": "pull_request", "parameters": {
        "required_approving_review_count": 0,
        "dismiss_stale_reviews_on_push": False,
        "require_code_owner_review": False,
        "require_last_push_approval": False,
        "required_review_thread_resolution": True,
        # omitting this defaults to allowing "merge", which required_linear_history rejects
        "allowed_merge_methods": ["squash", "rebase"],
    }})
payload = {
  "name": sys.argv[1],
  "target": "branch",
  "enforcement": "active",
  "conditions": {"ref_name": {"include": ["~DEFAULT_BRANCH"], "exclude": []}},
  "rules": rules,
}
for key in ("target", "conditions", "bypass_actors"):
    if key in current:
        payload[key] = current[key]
json.dump(payload, sys.stdout)' "$RULESET_NAME" "$require_pr_review" "$existing_json"
}

if [[ -n "$REPOS" ]]; then
  # shellcheck disable=SC2086  # word splitting is the point: one repo per line
  candidates=$(printf '%s\n' $REPOS | sed "s|^|PUBLIC false |")
else
  candidates=$(gh repo list "$OWNER" --limit 200 --json name,isArchived,isFork,visibility \
    --jq '.[] | select(.isArchived == false) | "\(.visibility) \(.isFork) \(.name)"')
fi

skipped_private=0
skipped_forks=0

while read -r visibility is_fork repo; do
  [[ -z "${repo:-}" ]] && continue

  # Rulesets on private repos need GitHub Pro; the API 403s on a free account.
  if [[ "$visibility" != "PUBLIC" ]]; then
    skipped_private=$((skipped_private + 1))
    continue
  fi

  if [[ "$is_fork" == "true" && "$INCLUDE_FORKS" != "1" ]]; then
    skipped_forks=$((skipped_forks + 1))
    continue
  fi

  # gh writes error bodies to stdout, so trust the exit status, not the output.
  if existing=$(gh api "repos/$OWNER/$repo/rulesets" \
        --jq "[.[] | select(.name == \"$RULESET_NAME\")] | first | .id // empty" 2>/dev/null); then
    :
  else
    echo "$OWNER/$repo: SKIP (rulesets unavailable)"
    continue
  fi

  had_pr=0
  current_json=""
  if [[ -n "$existing" ]]; then
    if current_json=$(gh api "repos/$OWNER/$repo/rulesets/$existing" 2>/dev/null); then
      types=$(jq -r '[.rules[].type] | join(" ")' <<< "$current_json")
      [[ " $types " == *" pull_request "* ]] && had_pr=1
    else
      echo "$OWNER/$repo: SKIP (cannot read ruleset $existing)"
      continue
    fi
  fi

  case "$REQUIRE_PR" in
    1) want_pr=1 ;;
    0) want_pr=0 ;;
    *) want_pr=$had_pr ;;
  esac

  if [[ "$DRY_RUN" == "1" ]]; then
    if [[ -n "$existing" ]]; then
      echo "$OWNER/$repo: would run: gh api -X PUT repos/$OWNER/$repo/rulesets/$existing --input - (pr=$want_pr)"
    else
      echo "$OWNER/$repo: would run: gh api -X POST repos/$OWNER/$repo/rulesets --input - (pr=$want_pr)"
    fi
    build_payload "$want_pr" "$current_json"
    echo
    continue
  fi

  if [[ -n "$existing" ]]; then
    build_payload "$want_pr" "$current_json" |
      gh api -X PUT "repos/$OWNER/$repo/rulesets/$existing" --input - --jq '"updated (pr='"$want_pr"')"' |
      sed "s|^|$OWNER/$repo: |"
  else
    build_payload "$want_pr" |
      gh api -X POST "repos/$OWNER/$repo/rulesets" --input - --jq '"created (pr='"$want_pr"')"' |
      sed "s|^|$OWNER/$repo: |"
  fi
done <<< "$candidates"

echo
echo "skipped: $skipped_private private (rulesets need GitHub Pro), $skipped_forks forks"
echo "Status checks are not set here: required check names differ per repo."
