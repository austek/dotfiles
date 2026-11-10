#!/bin/bash

# With --staged it scans the index instead of the working tree, which covers new files after `git add`.
# Fails when a tracked file hardcodes an absolute path into a user's home directory.
# Installers append these silently (opencode wrote /home/ali/.opencode/bin straight into
# the stowed .zshrc), and they are dead paths on every other machine.

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# Placeholder names and in-container paths that are not machine-specific.
ALLOWED='chrome|user|username|<user>'

repo_root=$(git rev-parse --show-toplevel) || exit 1
cd "$repo_root" || exit 1

grep_mode=()
scope="tracked"
case "${1:-}" in
    --staged) grep_mode=(--cached); scope="staged" ;;
    "") ;;
    *) echo "Usage: $0 [--staged]" >&2; exit 2 ;;
esac

echo "Checking $scope files for machine-specific home paths..."

MATCHES=$(git grep "${grep_mode[@]}" -nE '/(home|Users)/[A-Za-z0-9_.<>-]+' -- . \
    ':(exclude)zsh/.p10k.zsh' \
    ':(exclude)scripts/validate-no-machine-paths.sh' \
    | grep -vE "/(home|Users)/($ALLOWED)([^A-Za-z0-9_.-]|$)" || true)

if [[ -z "$MATCHES" ]]; then
    echo -e "${GREEN}None found.${NC}"
    exit 0
fi

echo -e "${RED}Machine-specific home paths found:${NC}"
printf '%s\n' "$MATCHES"
echo
echo -e "${YELLOW}Replace with \$HOME or ~. Inside a JSON hook command, double-quote it${NC}"
echo -e "${YELLOW}(\"\$HOME/...\") — single quotes stop the shell from expanding it.${NC}"
exit 1
