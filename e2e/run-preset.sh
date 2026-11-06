#!/usr/bin/env bash
# Runs inside the e2e container: installs a preset twice from a copy of the mounted repo, asserting after each run.
set -euo pipefail

preset=${1:?usage: run-preset.sh <work|personal|homelab>}
src=${E2E_SRC:-/src}
dest="$HOME/.dotfiles"
here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
optouts_file="$HOME/.config/dotfiles/packages/$preset.txt"
removed_package=tree

copy_repo() {
    mkdir -p "$dest"
    # Tracked plus untracked-but-not-ignored files: local edits are tested, the gitignored gradle cache is not copied.
    # A git worktree's .git points at a host path that is not mounted here, so it falls back to a plain copy.
    if git -c safe.directory="$src" -C "$src" rev-parse --git-dir >/dev/null 2>&1; then
        git -c safe.directory="$src" -C "$src" ls-files -z --cached --others --exclude-standard \
            | tar --null --ignore-failed-read -C "$src" -T - -cf - \
            | tar -xf - -C "$dest"
    else
        tar --exclude=./.git --exclude=./gradle/.gradle -C "$src" -cf - . | tar -xf - -C "$dest"
    fi
}

install_preset() {
    local log
    log=$(mktemp)
    "$dest/bin/dotfiles-setup" install --preset "$preset" --force -v "$@" < /dev/null 2>&1 | tee "$log"
    # Tool installers log an error and carry on, so the exit status alone hides a failed install.
    if grep -qF '[ERROR]' "$log"; then
        echo "e2e[$preset]: install logged errors:" >&2
        grep -F '[ERROR]' "$log" >&2
        return 1
    fi
    last_install_log=$log
}

main() {
    copy_repo
    cd "$dest"
    # The install's first apt-get install assumes the package lists already exist, as they do on a real machine.
    sudo apt-get update -qq

    echo "=== e2e[$preset]: first install ==="
    install_preset
    "$here/assert-preset.sh" "$preset" first "$removed_package"

    echo "=== e2e[$preset]: user opts out of '$removed_package' ==="
    mkdir -p "$(dirname "$optouts_file")"
    printf '%s\n' '# dotfiles-setup opt-outs v1' "$removed_package" > "$optouts_file"
    "$here/assert-preset.sh" "$preset" snapshot

    echo "=== e2e[$preset]: second install ==="
    install_preset --prune
    # The opt-out removal must be the system stage's only reason to run.
    grep -qF 'System stage needed: 1 apt package(s) pending removal.' "$last_install_log" \
        || { echo "ASSERT FAILED [$preset/second]: the system stage did not run for the opt-out removal alone" >&2; return 1; }
    "$here/assert-preset.sh" "$preset" second "$removed_package"

    echo "=== e2e[$preset]: PASS ==="
}

main