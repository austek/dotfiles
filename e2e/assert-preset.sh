#!/usr/bin/env bash
# Usage: assert-preset.sh <preset> <first|snapshot|second> [package opted out before the second run]
set -euo pipefail

preset=${1:?preset required}
phase=${2:?phase required}
removed_package=${3:-}
config_dir="$HOME/.config/dotfiles"
state_json="$config_dir/state.json"
optouts_file="$config_dir/packages/$preset.txt"
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

applied() {
    local package=$1
    python3 -I -c 'import json,sys; sys.exit(0 if sys.argv[2] in json.load(open(sys.argv[1]))["applied_package_names"] else 1)' \
        "$state_json" "$package"
}

dpkg_installed() {
    local package=$1
    [[ $(dpkg-query -W -f="\${db:Status-Abbrev}" "$package" 2>/dev/null) == ii* ]]
}

source_host() {
    local source_file=$1
    grep -m1 '^URIs:' "$source_file" | sed -E 's|^URIs:[[:space:]]*https?://([^/[:space:]]+).*|\1|'
}

assert_source_installed() {
    local package=$1 installed=$2 tracked=$3
    [[ -e "$installed" ]] || fail "$installed is missing although '$package' is selected"
    if [[ -L "$installed" ]]; then
        [[ $(readlink -f "$installed") == "$tracked" ]] || fail "$installed does not link to the checkout"
    elif [[ $package == google-chrome-stable ]]; then
        # Google Chrome's postinst replaces the stowed symlink with its own file for the same repository.
        [[ $(source_host "$installed") == "$(source_host "$tracked")" ]] || fail "$installed points at a different host than the checkout"
    else
        fail "$installed is not linked although '$package' is selected"
    fi
}

assert_apt_sources_follow_the_preset() {
    local sources_dir=/etc/apt/sources.list.d
    local tracked_dir="$HOME/.dotfiles/apt$sources_dir"
    local pair package file
    for pair in 1password:1password.sources google-chrome-stable:google-chrome.sources code:vscode.sources gh:github-cli.sources; do
        package=${pair%%:*}
        file=${pair#*:}
        [[ -f "$tracked_dir/$file" ]] || fail "tracked source $file is missing from the checkout"
        if applied "$package"; then
            assert_source_installed "$package" "$sources_dir/$file" "$tracked_dir/$file"
        else
            [[ ! -e "$sources_dir/$file" && ! -L "$sources_dir/$file" ]] || fail "$file is linked although '$package' is not selected"
        fi
    done
}

assert_installed_state() {
    [[ -f "$state_json" ]] || fail "state.json missing"
    python3 -I -c 'import json,sys; sys.exit(0 if json.load(open(sys.argv[1])).get("preset_name") == sys.argv[2] else 1)' \
        "$state_json" "$preset" || fail "state.json does not record preset '$preset'"
    [[ -n "$removed_package" ]] || fail "phase $phase needs the opted-out package name"
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

assert_fresh_install_writes_no_optouts() {
    [[ ! -e "$optouts_file" ]] || fail "a fresh install wrote $optouts_file"
    applied "$removed_package" || fail "state.json does not list '$removed_package' as applied"
    dpkg_installed "$removed_package" || fail "'$removed_package' is not installed"
}

assert_optout_removed() {
    cmp -s "$snapshot_dir/optouts.txt" "$optouts_file" || fail "second run changed the opt-out file $optouts_file"
    ! dpkg_installed "$removed_package" || fail "opted-out '$removed_package' is still installed"
    ! applied "$removed_package" || fail "state.json still lists opted-out '$removed_package' as applied"
}

assert_idempotent_second_run() {
    [[ -d "$snapshot_dir" ]] || fail "no snapshot to compare against"
    cmp -s "$snapshot_dir/settings.json" "$settings" || fail "second run rewrote $settings"
    [[ $(file_identity "$settings") == "$(cat "$snapshot_dir/settings.identity")" ]] \
        || fail "second run replaced $settings with identical content"
    assert_optout_removed
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
    cp "$optouts_file" "$snapshot_dir/optouts.txt"
}

case $phase in
    first) assert_installed_state; assert_fresh_install_writes_no_optouts ;;
    snapshot) take_snapshot ;;
    second) assert_installed_state; assert_idempotent_second_run ;;
    *) fail "unknown phase '$phase'" ;;
esac

echo "assert[$preset/$phase]: ok"
