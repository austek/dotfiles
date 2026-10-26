#!/usr/bin/env bash
# Runs inside the e2e container: installs a preset twice from a copy of the mounted repo, asserting after each run.
set -euo pipefail

preset=${1:?usage: run-preset.sh <work|personal|homelab>}
src=${E2E_SRC:-/src}
dest="$HOME/.dotfiles"
here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
forked="$HOME/.config/dotfiles/packages/$preset.txt"
removed_package=tree

copy_repo() {
    mkdir -p "$dest"
    # Tracked plus untracked-but-not-ignored files: local edits are tested, the gitignored gradle cache is not copied.
    git -c safe.directory="$src" -C "$src" ls-files -z --cached --others --exclude-standard \
        | tar --null --ignore-failed-read -C "$src" -T - -cf - \
        | tar -xf - -C "$dest"
}

install_preset() {
    "$dest/bin/dotfiles-setup" install --preset "$preset" --force -v < /dev/null
}

main() {
    copy_repo
    cd "$dest"
    # The install's first apt-get install assumes the package lists already exist, as they do on a real machine.
    sudo apt-get update -qq

    echo "=== e2e[$preset]: first install ==="
    install_preset
    "$here/assert-preset.sh" "$preset" first

    echo "=== e2e[$preset]: user removes '$removed_package' from the forked package list ==="
    grep -qx "$removed_package" "$forked"
    sed -i "/^$removed_package\$/d" "$forked"
    "$here/assert-preset.sh" "$preset" snapshot

    echo "=== e2e[$preset]: second install ==="
    install_preset
    "$here/assert-preset.sh" "$preset" second "$removed_package"

    echo "=== e2e[$preset]: PASS ==="
}

main