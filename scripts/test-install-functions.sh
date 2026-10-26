#!/bin/bash
# shellcheck disable=SC2329,SC2034,SC2317
# Regression harness for the shell functions setup.sh still owns.
# Sourcing setup.sh here does not run main() — see the sourceability guard
# at the bottom of setup.sh.

set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
DOTFILES_DIR=$(dirname "$SCRIPT_DIR")
REAL_HOME="$HOME"

# shellcheck source=/dev/null
source "$DOTFILES_DIR/bin/setup.sh"

# Assertions below check log_info/log_success output, which setup.sh gates behind
# VERBOSITY>=1 (default 0) since it added -v/-vv/-vvv flags.
VERBOSITY=1

PASS_COUNT=0
FAIL_COUNT=0
FAILURES=()
STUB_DIR=""

assert_contains() {
    local haystack="$1" needle="$2" scenario="$3"
    if [[ "$haystack" == *"$needle"* ]]; then
        PASS_COUNT=$((PASS_COUNT + 1))
    else
        FAIL_COUNT=$((FAIL_COUNT + 1))
        FAILURES+=("$scenario: expected output to contain '$needle', got: $haystack")
    fi
}

capture() {
    exit_code=0
    output=$("$@" 2>&1) || exit_code=$?
}

assert_exit_code() {
    local actual="$1" expected="$2" scenario="$3"
    if [[ "$actual" -eq "$expected" ]]; then
        PASS_COUNT=$((PASS_COUNT + 1))
    else
        FAIL_COUNT=$((FAIL_COUNT + 1))
        FAILURES+=("$scenario: expected exit code $expected, got $actual")
    fi
}

reset_stubs() {
    rm -rf -- "$STUB_DIR"
    STUB_DIR=$(mktemp -d)
    HOME="$STUB_DIR/fake_home"
    mkdir -p "$HOME"
    ROLLBACK_LOG="$HOME/.dotfiles-setup-rollback.log"
    DRY_RUN=false
}

SCENARIOS=()
register_scenario() { SCENARIOS+=("$1"); }

test_detect_ubuntu_codename_reads_os_release() {
    local fake_os_release="$STUB_DIR/os-release"
    cat > "$fake_os_release" <<'EOF'
NAME="Ubuntu"
VERSION_CODENAME=resolute
EOF
    local output
    output=$(detect_ubuntu_codename "$fake_os_release" 2>&1)
    assert_contains "$output" "resolute" "detect_ubuntu_codename reads VERSION_CODENAME"
}
register_scenario test_detect_ubuntu_codename_reads_os_release

test_detect_ubuntu_codename_missing_file() {
    local output
    output=$(detect_ubuntu_codename "$STUB_DIR/does-not-exist" 2>&1)
    assert_contains "$output" "Could not detect Ubuntu codename" "detect_ubuntu_codename missing-file warns"
    assert_contains "$output" "noble" "detect_ubuntu_codename missing-file falls back to noble"
}
register_scenario test_detect_ubuntu_codename_missing_file

test_detect_ubuntu_codename_empty_var() {
    local fake_os_release="$STUB_DIR/os-release"
    cat > "$fake_os_release" <<'EOF'
NAME="Ubuntu"
EOF
    local output
    output=$(detect_ubuntu_codename "$fake_os_release" 2>&1)
    assert_contains "$output" "Could not detect Ubuntu codename" "detect_ubuntu_codename empty-var warns"
    assert_contains "$output" "noble" "detect_ubuntu_codename empty-var falls back to noble"
}
register_scenario test_detect_ubuntu_codename_empty_var

for scenario in "${SCENARIOS[@]}"; do
    reset_stubs
    "$scenario"
done
rm -rf -- "$STUB_DIR"
HOME="$REAL_HOME"

# --- determine_packages_to_install with --package-file override ---
PACKAGE_FILE_OVERRIDE=""
TMP_PKG_FILE=$(mktemp)
printf '# comment\nfoo\nbar\n\nbar\n' > "$TMP_PKG_FILE"
PACKAGE_FILE_OVERRIDE="$TMP_PKG_FILE"
PACKAGES_TO_INSTALL=()
determine_packages_to_install >/dev/null 2>&1
assert_contains "${PACKAGES_TO_INSTALL[*]}" "foo" "package-file override: includes foo"
assert_contains "${PACKAGES_TO_INSTALL[*]}" "bar" "package-file override: includes bar"
if [[ "${#PACKAGES_TO_INSTALL[@]}" -eq 2 ]]; then
    PASS_COUNT=$((PASS_COUNT + 1))
else
    FAIL_COUNT=$((FAIL_COUNT + 1))
    FAILURES+=("package-file override: expected 2 deduped packages, got ${#PACKAGES_TO_INSTALL[@]}")
fi
rm -f "$TMP_PKG_FILE"
PACKAGE_FILE_OVERRIDE=""

# --- determine_packages_to_install rejects an unreadable --package-file ---
TMP_PKG_FILE=$(mktemp)
chmod 000 "$TMP_PKG_FILE"
PACKAGE_FILE_OVERRIDE="$TMP_PKG_FILE"
if [[ "$EUID" -ne 0 ]] && (determine_packages_to_install >/dev/null 2>&1); then
    FAIL_COUNT=$((FAIL_COUNT + 1))
    FAILURES+=("package-file override: unreadable file was accepted")
else
    PASS_COUNT=$((PASS_COUNT + 1))
fi
rm -f "$TMP_PKG_FILE"
PACKAGE_FILE_OVERRIDE=""

# --- validate_machine_preset accepts a non-standard name only with --package-file ---
MACHINE_PRESET="laptop-minimal"
PACKAGE_FILE_OVERRIDE="/tmp/does-not-need-to-exist-for-this-check"
if validate_machine_preset >/dev/null 2>&1; then
    PASS_COUNT=$((PASS_COUNT + 1))
else
    FAIL_COUNT=$((FAIL_COUNT + 1))
    FAILURES+=("validate_machine_preset: custom preset name rejected despite --package-file")
fi
PACKAGE_FILE_OVERRIDE=""
MACHINE_PRESET=""

# --- validate_machine_preset rejects a missing --package-file ---
MACHINE_PRESET="work"
PACKAGE_FILE_OVERRIDE=""
if (validate_machine_preset >/dev/null 2>&1); then
    FAIL_COUNT=$((FAIL_COUNT + 1))
    FAILURES+=("validate_machine_preset: accepted a preset without --package-file")
else
    PASS_COUNT=$((PASS_COUNT + 1))
fi
MACHINE_PRESET=""

# --- stow backup helpers (--force-stow) ---
check() {
    local scenario="$1"
    shift
    if "$@"; then
        PASS_COUNT=$((PASS_COUNT + 1))
    else
        FAIL_COUNT=$((FAIL_COUNT + 1))
        FAILURES+=("$scenario")
    fi
}

stow_sandbox() {
    STOW_TMP=$(mktemp -d)
    HOME="$STOW_TMP/home"
    mkdir -p "$HOME"
}

stow_teardown() {
    rm -rf "$STOW_TMP"
    HOME="$REAL_HOME"
}

# --- apt sources: unneeded files are ignored, never moved out of the repo ---
stow_sandbox
mkdir -p "$STOW_TMP/repo/apt/etc/apt/sources.list.d"
for f in 1password.sources google-chrome.sources vscode.sources github-cli.sources; do
    : > "$STOW_TMP/repo/apt/etc/apt/sources.list.d/$f"
done
stow_calls="$STOW_TMP/stow_calls"
sudo() { printf '%s\n' "$*" >> "$stow_calls"; }
(
    DOTFILES_DIR="$STOW_TMP/repo"
    PACKAGES_TO_INSTALL=(gh)
    stow_apt_source_files
) >/dev/null 2>&1 || true
check "apt stow: unneeded sources are passed to stow --ignore" grep -q -- '--ignore=1password\\.sources\$' "$stow_calls"
check "apt stow: needed source is not ignored" test -z "$(grep -- 'github-cli' "$stow_calls" || true)"
check "apt stow: repo checkout keeps every tracked source" test "$(command find "$STOW_TMP/repo/apt" -name '*.sources' | wc -l)" -eq 4
unset -f sudo
stow_teardown

# --- deselected rendered apt sources are removed; hand-made ones are not ---
stow_sandbox
APT_SOURCES_DIR="$STOW_TMP/sources.list.d"
mkdir -p "$APT_SOURCES_DIR"
printf '%s\nTypes: deb\n' "$APT_RENDERED_MARKER" > "$APT_SOURCES_DIR/pgadmin4.sources"
printf '%s\nTypes: deb\n' "$APT_RENDERED_MARKER" > "$APT_SOURCES_DIR/docker.sources"
printf 'Types: deb\n' > "$APT_SOURCES_DIR/postgresql.sources"
sudo() { "$@"; }
remove_deselected_rendered_sources 1 0 0 1 >/dev/null 2>&1
check "apt sources: deselected rendered source is removed" test ! -e "$APT_SOURCES_DIR/pgadmin4.sources"
check "apt sources: selected rendered source is kept" test -e "$APT_SOURCES_DIR/docker.sources"
check "apt sources: hand-made source without the marker is kept" test -e "$APT_SOURCES_DIR/postgresql.sources"
unset -f sudo
unset APT_SOURCES_DIR
stow_teardown

# --- --only / --list-steps step selection ---
ONLY_STEPS=()
check "steps: every step is selected without --only" step_selected install_packages
ONLY_STEPS=(install_packages)
check "steps: --only selects a listed step" step_selected install_packages
if step_selected configure_docker_group; then
    FAIL_COUNT=$((FAIL_COUNT + 1))
    FAILURES+=("steps: --only selected an unlisted step")
else
    PASS_COUNT=$((PASS_COUNT + 1))
fi
ONLY_STEPS=(not_a_step)
if (validate_only_steps >/dev/null 2>&1); then
    FAIL_COUNT=$((FAIL_COUNT + 1))
    FAILURES+=("steps: validate_only_steps accepted an unknown step")
else
    PASS_COUNT=$((PASS_COUNT + 1))
fi
ONLY_STEPS=()
check "steps: --list-steps prints steps in run order" test "$(bash "$SCRIPT_DIR/setup.sh" --list-steps | head -n 1)" = "install_core_deps"

# --- a partial run keeps the rollback log for the next segment ---
ROLLBACK_LOG=$(mktemp)
echo "change" > "$ROLLBACK_LOG"
KEEP_ROLLBACK_LOG=true
( cleanup 0 ) >/dev/null 2>&1
check "steps: partial run keeps the rollback log" test -s "$ROLLBACK_LOG"
KEEP_ROLLBACK_LOG=false
( cleanup 0 ) >/dev/null 2>&1
check "steps: final run removes the rollback log" test ! -e "$ROLLBACK_LOG"
rm -f "$ROLLBACK_LOG"

echo
echo "Passed: $PASS_COUNT  Failed: $FAIL_COUNT"
if [[ "$FAIL_COUNT" -gt 0 ]]; then
    printf 'FAILURES:\n'
    printf '  - %s\n' "${FAILURES[@]}"
    exit 1
fi
exit 0
