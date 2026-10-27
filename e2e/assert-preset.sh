#!/usr/bin/env bash
# Usage: assert-preset.sh <preset> <first|snapshot|second> [package removed from the forked list before the second run]
set -euo pipefail

preset=${1:?preset required}
phase=${2:?phase required}
removed_package=${3:-}
config_dir="$HOME/.config/dotfiles"
forked="$config_dir/packages/$preset.txt"
settings="$HOME/.claude/settings.json"
snapshot_dir=${E2E_SNAPSHOT_DIR:-/tmp/e2e-snapshot}

fail() {
    echo "ASSERT FAILED [$preset/$phase]: $*" >&2
    exit 1
}

assert_symlink_into_repo() {
    local link=$1
    [[ -L "$link" ]] || fail "$link is not a symlink"
    [[ -e "$link" ]] || fail "$link is a dangling symlink"
    [[ $(readlink -f "$link") == "$HOME/.dotfiles/"* ]] || fail "$link does not resolve into ~/.dotfiles"
}

assert_apt_sources_follow_the_preset() {
    local sources_dir=/etc/apt/sources.list.d
    local tracked_dir="$HOME/.dotfiles/apt$sources_dir"
    local pair package file
    for pair in 1password:1password.sources google-chrome-stable:google-chrome.sources code:vscode.sources gh:github-cli.sources; do
        package=${pair%%:*}
        file=${pair#*:}
        [[ -f "$tracked_dir/$file" ]] || fail "tracked source $file is missing from the checkout"
        if grep -qx "$package" "$forked"; then
            [[ -L "$sources_dir/$file" ]] || fail "$file is not linked although '$package' is selected"
            [[ $(readlink -f "$sources_dir/$file") == "$tracked_dir/$file" ]] || fail "$file does not link to the checkout"
        else
            [[ ! -e "$sources_dir/$file" && ! -L "$sources_dir/$file" ]] || fail "$file is linked although '$package' is not selected"
        fi
    done
}

assert_installed_state() {
    [[ -f "$config_dir/state.json" ]] || fail "state.json missing"
    python3 -I -c 'import json,sys; sys.exit(0 if json.load(open(sys.argv[1])).get("preset_name") == sys.argv[2] else 1)' \
        "$config_dir/state.json" "$preset" || fail "state.json does not record preset '$preset'"
    [[ -s "$forked" ]] || fail "forked package list $forked missing or empty"
    python3 -I -c 'import json,sys; json.load(open(sys.argv[1]))' "$settings" || fail "$settings is not valid JSON"
    assert_symlink_into_repo "$HOME/.zshrc"
    assert_symlink_into_repo "$HOME/.gitconfig"
    [[ -f /etc/apt/preferences.d/nosnap.pref ]] || fail "snapd block preference missing"
    assert_apt_sources_follow_the_preset
    ! dpkg -s snapd >/dev/null 2>&1 || fail "snapd is installed"
    local tool
    for tool in zsh stow tmux git; do
        command -v "$tool" >/dev/null || fail "$tool not on PATH"
    done
}

assert_idempotent_second_run() {
    [[ -d "$snapshot_dir" ]] || fail "no snapshot to compare against"
    cmp -s "$snapshot_dir/settings.json" "$settings" || fail "second run rewrote $settings"
    [[ $(file_identity "$settings") == "$(cat "$snapshot_dir/settings.identity")" ]] \
        || fail "second run replaced $settings with identical content"
    cmp -s "$snapshot_dir/forked.txt" "$forked" || fail "second run changed the forked package list"
    [[ -n "$removed_package" ]] || fail "second phase needs the removed package name"
    ! grep -qx "$removed_package" "$forked" || fail "second run re-added '$removed_package' to the forked list"
    compgen -G "$HOME/.claude/settings.json.bak-*" >/dev/null && fail "second run backed up settings.json"
    return 0
}

file_identity() {
    local file=$1
    stat -c '%i %y' "$file"
}

take_snapshot() {
    mkdir -p "$snapshot_dir"
    cp "$settings" "$snapshot_dir/settings.json"
    file_identity "$settings" > "$snapshot_dir/settings.identity"
    cp "$forked" "$snapshot_dir/forked.txt"
}

case $phase in
    first) assert_installed_state ;;
    snapshot) take_snapshot ;;
    second) assert_installed_state; assert_idempotent_second_run ;;
    *) fail "unknown phase '$phase'" ;;
esac

echo "assert[$preset/$phase]: ok"
