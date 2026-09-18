#!/bin/bash

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

if ! command -v shellcheck &> /dev/null; then
    echo -e "${YELLOW}Warning: shellcheck is not installed${NC}"
    echo "shellcheck is a managed package (packages/apt_common.txt); run 'dotfiles-setup install --preset <preset>' to install it."
    exit 1
fi

echo "Running shellcheck validation..."

SHELL_FILES=()
while IFS= read -r -d '' file; do
    # Check if it's actually a bash/sh script, not zsh
    FIRST_LINE=$(head -n 1 "$file" 2>/dev/null || true)
    if [[ "$FIRST_LINE" =~ ^#!.*/bash ]] || [[ "$FIRST_LINE" =~ ^#!.*/sh ]] || [[ "$file" == *.sh && ! "$FIRST_LINE" =~ zsh ]]; then
        SHELL_FILES+=("$file")
    fi
done < <(find . -path "./gradle/.gradle" -prune -o -type f \( -name "*.sh" -o -name "*.bash" \) -not -path "./.git/*" -not -path "*/.oh-my-zsh/*" -not -path "*/p10k.zsh" -not -path "*/shellcheck-stable/*" -print0)

# Also check files with bash/sh shebang (exclude zsh)
while IFS= read -r -d '' file; do
    if [[ -f "$file" && -x "$file" ]]; then
        FIRST_LINE=$(head -n 1 "$file" 2>/dev/null || true)
        if [[ "$FIRST_LINE" =~ ^#!.*/bash$ ]] || [[ "$FIRST_LINE" =~ ^#!.*/sh$ ]]; then
            SHELL_FILES+=("$file")
        fi
    fi
done < <(find . -path "./gradle/.gradle" -prune -o -type f -executable -not -path "./.git/*" -not -path "*/.oh-my-zsh/*" -not -path "*/shellcheck-stable/*" -print0)

readarray -t UNIQUE_FILES < <(printf '%s\n' "${SHELL_FILES[@]}" | sort -u)

if [[ ${#UNIQUE_FILES[@]} -eq 0 ]]; then
    echo -e "${YELLOW}No shell scripts found${NC}"
    exit 0
fi

echo "Found ${#UNIQUE_FILES[@]} shell script(s) to check:"
printf '%s\n' "${UNIQUE_FILES[@]}"
echo

FAILED_FILES=()
for file in "${UNIQUE_FILES[@]}"; do
    echo -n "Checking $file... "
    if shellcheck "$file"; then
        echo -e "${GREEN}✓${NC}"
    else
        echo -e "${RED}✗${NC}"
        FAILED_FILES+=("$file")
    fi
done

echo

if [[ ${#FAILED_FILES[@]} -eq 0 ]]; then
    echo -e "${GREEN}All shell scripts passed shellcheck validation!${NC}"
    exit 0
else
    echo -e "${RED}The following files failed shellcheck validation:${NC}"
    printf '%s\n' "${FAILED_FILES[@]}"
    echo
    echo -e "${YELLOW}Run 'shellcheck <filename>' for detailed information about issues${NC}"
    exit 1
fi
