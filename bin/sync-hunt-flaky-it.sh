#!/bin/bash
#
# Pushes the hunt-flaky-it skill from this dotfiles checkout into the iam repo.
#
# dotfiles is the source of truth for claude/.claude/skills/hunt-flaky-it;
# this one-way sync overwrites iam's working tree so the change can be
# reviewed there. Never hand-edit files under $IAM_REPO/.claude/skills/hunt-flaky-it.

set -euo pipefail

IAM_REPO="${IAM_REPO:-$HOME/Workspace/teamaf/iam}"
SKILL_REL=".claude/skills/hunt-flaky-it"
SRC="$(git -C "$(dirname "$0")" rev-parse --show-toplevel)/claude/$SKILL_REL"
DEST="$IAM_REPO/$SKILL_REL"

if [[ ! -d "$IAM_REPO/.git" ]]; then
    echo "hunt-flaky-it: no iam checkout at $IAM_REPO, nothing to push." >&2
    exit 0
fi

# dev-aws/*-secret.yaml are real credentials, gitignored in iam and never present in
# this checkout. Exclude them so --delete doesn't wipe out iam's local copies.
EXCLUDE_FILE="$SRC/dev-aws/.gitignore"
if [[ ! -f "$EXCLUDE_FILE" ]]; then
    echo "hunt-flaky-it: $EXCLUDE_FILE missing, refusing to push (would risk deleting iam's local secrets)." >&2
    exit 1
fi

mkdir -p "$DEST"

# Also protect any other destination-only file iam's own git already treats as
# ignored/untracked under this path (e.g. local notes, secrets not covered by
# dotfiles' dev-aws/.gitignore above) -- resolved from iam's own git config,
# not guessed from this checkout, so it stays correct if iam's ignore rules
# ever diverge from dotfiles'.
DEST_EXCLUDES=()
while IFS= read -r -d '' rel; do
    DEST_EXCLUDES+=(--exclude="${rel#"$SKILL_REL"/}")
done < <(git -C "$IAM_REPO" ls-files --others --ignored --exclude-standard -z -- "$SKILL_REL")

rsync -a --delete --exclude-from="$EXCLUDE_FILE" "${DEST_EXCLUDES[@]}" "$SRC/" "$DEST/"

echo "hunt-flaky-it: pushed into $DEST."
