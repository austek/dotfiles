#!/bin/bash
# shellcheck disable=SC2329,SC2034,SC2317
# Regression harness for setup.sh's install_from_url-based installers.
# Sourcing setup.sh here does not run main() — see the sourceability guard
# at the bottom of setup.sh.

set -uo pipefail

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

assert_exit_code() {
    local actual="$1" expected="$2" scenario="$3"
    if [ "$actual" -eq "$expected" ]; then
        PASS_COUNT=$((PASS_COUNT + 1))
    else
        FAIL_COUNT=$((FAIL_COUNT + 1))
        FAILURES+=("$scenario: expected exit code $expected, got $actual")
    fi
}

assert_called() {
    local marker="$1" scenario="$2" what="$3"
    if [ -f "$STUB_DIR/$marker" ]; then
        PASS_COUNT=$((PASS_COUNT + 1))
    else
        FAIL_COUNT=$((FAIL_COUNT + 1))
        FAILURES+=("$scenario: expected $what to be called, but it wasn't")
    fi
}

assert_not_called() {
    local marker="$1" scenario="$2" what="$3"
    if [ ! -f "$STUB_DIR/$marker" ]; then
        PASS_COUNT=$((PASS_COUNT + 1))
    else
        FAIL_COUNT=$((FAIL_COUNT + 1))
        FAILURES+=("$scenario: expected $what NOT to be called, but it was")
    fi
}


curl() {
    touch "$STUB_DIR/curl_called"
    if [ "${STUB_CURL_FAIL:-false}" = true ]; then
        return 1
    fi
    printf '%s' "${STUB_CURL_OUTPUT:-}"
}

download_with_cache() {
    touch "$STUB_DIR/download_called"
    DOWNLOAD_CACHE_HIT=false
    if [ "${STUB_DOWNLOAD_FAIL:-false}" = true ]; then
        return 1
    fi
    : > "$4"
    return 0
}

sudo() {
    touch "$STUB_DIR/sudo_called"
    "$@"
}

tar() {
    touch "$STUB_DIR/tar_called"
    if [ "${STUB_EXTRACT_FAIL:-false}" = true ]; then
        return 1
    fi
    return 0
}

unzip() {
    touch "$STUB_DIR/unzip_called"
    if [ "${STUB_EXTRACT_FAIL:-false}" = true ]; then
        return 1
    fi
    # install_awscli_step runs "$temp_dir/aws/install" directly, with no stubbed
    # command in between, so this unzip stub must materialize whatever the
    # scenario staged under $STUB_DIR/aws into the real dest dir (-d DEST).
    local dest_dir="${*: -1}"
    [ -d "$STUB_DIR/aws" ] && cp -r "$STUB_DIR/aws" "$dest_dir/"
    return 0
}

dpkg() {
    touch "$STUB_DIR/dpkg_called"
    if [ "$1" = "-i" ]; then
        if [ "${STUB_DPKG_INSTALL_FAIL:-false}" = true ]; then
            return 1
        fi
        return 0
    fi
    if [ "$1" = "-l" ]; then
        if [ "${STUB_DPKG_INSTALLED:-false}" = true ]; then
            echo "ii  ${STUB_DPKG_LIST_NAME:-fake-package}  1.0"
        fi
        return 0
    fi
    return 0
}

apt-get() {
    touch "$STUB_DIR/apt_get_called"
    return 0
}

install() {
    touch "$STUB_DIR/install_called"
    if [ "${STUB_INSTALL_FAIL:-false}" = true ]; then
        return 1
    fi
    return 0
}

find() {
    touch "$STUB_DIR/find_called"
    if [ "${STUB_FIND_EMPTY:-false}" = true ]; then
        return 0
    fi
    printf '%s/jetbrains-toolbox/jetbrains-toolbox\n' "$STUB_DIR"
}

reset_stubs() {
    rm -rf -- "$STUB_DIR"
    STUB_DIR=$(mktemp -d)
    HOME="$STUB_DIR/fake_home"
    mkdir -p "$HOME"
    ROLLBACK_LOG="$HOME/.dotfiles-setup-rollback.log"
    unset STUB_CURL_FAIL STUB_CURL_OUTPUT STUB_DOWNLOAD_FAIL STUB_EXTRACT_FAIL \
          STUB_DPKG_INSTALL_FAIL STUB_DPKG_INSTALLED STUB_DPKG_LIST_NAME STUB_INSTALL_FAIL \
          STUB_FIND_EMPTY STUB_ALREADY_INSTALLED
    DRY_RUN=false

    # Stubs replace each tool's real already-installed check (`command -v`,
    # `dpkg -l`, etc.) so "not installed" scenarios aren't flaky on a machine
    # that has the tool for real. check_fn's own logic isn't exercised here.
    lazydocker_is_installed() { [ "${STUB_ALREADY_INSTALLED:-false}" = true ]; }
    istioctl_is_installed() { [ "${STUB_ALREADY_INSTALLED:-false}" = true ]; }
    zoom_is_installed() { [ "${STUB_ALREADY_INSTALLED:-false}" = true ]; }
    slack_is_installed() { [ "${STUB_ALREADY_INSTALLED:-false}" = true ]; }
    jetbrains_toolbox_is_installed() { [ "${STUB_ALREADY_INSTALLED:-false}" = true ]; }
    awscli_is_installed() { [ "${STUB_ALREADY_INSTALLED:-false}" = true ]; }
}

SCENARIOS=()
register_scenario() { SCENARIOS+=("$1"); }

test_lazydocker_already_installed() {
    STUB_ALREADY_INSTALLED=true
    local output exit_code
    output=$(install_lazydocker 2>&1); exit_code=$?
    assert_contains "$output" "already installed. Skipping." "lazydocker already-installed"
    assert_exit_code "$exit_code" 0 "lazydocker already-installed"
    assert_not_called "curl_called" "lazydocker already-installed" "curl"
}
register_scenario test_lazydocker_already_installed

test_lazydocker_dry_run() {
    DRY_RUN=true
    local output exit_code
    output=$(install_lazydocker 2>&1); exit_code=$?
    assert_contains "$output" "[DRY-RUN]" "lazydocker dry-run"
    assert_exit_code "$exit_code" 0 "lazydocker dry-run"
    assert_not_called "curl_called" "lazydocker dry-run" "curl"
}
register_scenario test_lazydocker_dry_run

test_lazydocker_resolve_fail() {
    STUB_CURL_OUTPUT=""
    local output exit_code
    output=$(install_lazydocker 2>&1); exit_code=$?
    assert_contains "$output" "Failed to resolve lazydocker download URL." "lazydocker resolve-fail"
    assert_exit_code "$exit_code" 0 "lazydocker resolve-fail"
    assert_not_called "download_called" "lazydocker resolve-fail" "download_with_cache"
}
register_scenario test_lazydocker_resolve_fail

test_lazydocker_download_fail() {
    STUB_CURL_OUTPUT='"tag_name": "v1.2.3"'
    STUB_DOWNLOAD_FAIL=true
    local output exit_code
    output=$(install_lazydocker 2>&1); exit_code=$?
    assert_contains "$output" "Failed to download lazydocker" "lazydocker download-fail"
    assert_exit_code "$exit_code" 0 "lazydocker download-fail"
    assert_not_called "tar_called" "lazydocker download-fail" "tar"
}
register_scenario test_lazydocker_download_fail

test_lazydocker_extract_fail() {
    STUB_CURL_OUTPUT='"tag_name": "v1.2.3"'
    STUB_EXTRACT_FAIL=true
    local output exit_code
    output=$(install_lazydocker 2>&1); exit_code=$?
    assert_contains "$output" "Failed to extract lazydocker from tarball." "lazydocker extract-fail"
    assert_exit_code "$exit_code" 0 "lazydocker extract-fail"
    assert_not_called "install_called" "lazydocker extract-fail" "install"
}
register_scenario test_lazydocker_extract_fail

test_lazydocker_install_fail() {
    STUB_CURL_OUTPUT='"tag_name": "v1.2.3"'
    STUB_INSTALL_FAIL=true
    local output exit_code
    output=$(install_lazydocker 2>&1); exit_code=$?
    assert_contains "$output" "Failed to install lazydocker." "lazydocker install-fail"
    assert_exit_code "$exit_code" 0 "lazydocker install-fail"
}
register_scenario test_lazydocker_install_fail

test_lazydocker_success() {
    STUB_CURL_OUTPUT='"tag_name": "v1.2.3"'
    local output exit_code
    output=$(install_lazydocker 2>&1); exit_code=$?
    assert_contains "$output" "lazydocker installed successfully v1.2.3." "lazydocker success"
    assert_exit_code "$exit_code" 0 "lazydocker success"
    assert_called "install_called" "lazydocker success" "install"
}
register_scenario test_lazydocker_success

test_istioctl_already_installed() {
    STUB_ALREADY_INSTALLED=true
    local output exit_code
    output=$(install_istioctl 2>&1); exit_code=$?
    assert_contains "$output" "already installed. Skipping." "istioctl already-installed"
    assert_exit_code "$exit_code" 0 "istioctl already-installed"
    assert_not_called "curl_called" "istioctl already-installed" "curl"
}
register_scenario test_istioctl_already_installed

test_istioctl_dry_run() {
    DRY_RUN=true
    local output exit_code
    output=$(install_istioctl 2>&1); exit_code=$?
    assert_contains "$output" "[DRY-RUN]" "istioctl dry-run"
    assert_exit_code "$exit_code" 0 "istioctl dry-run"
    assert_not_called "curl_called" "istioctl dry-run" "curl"
}
register_scenario test_istioctl_dry_run

test_istioctl_resolve_fail() {
    STUB_CURL_OUTPUT=""
    local output exit_code
    output=$(install_istioctl 2>&1); exit_code=$?
    assert_contains "$output" "Failed to resolve istioctl download URL." "istioctl resolve-fail"
    assert_exit_code "$exit_code" 0 "istioctl resolve-fail"
    assert_not_called "download_called" "istioctl resolve-fail" "download_with_cache"
}
register_scenario test_istioctl_resolve_fail

test_istioctl_download_fail() {
    STUB_CURL_OUTPUT='"tag_name": "1.20.0"'
    STUB_DOWNLOAD_FAIL=true
    local output exit_code
    output=$(install_istioctl 2>&1); exit_code=$?
    assert_contains "$output" "Failed to download istioctl" "istioctl download-fail"
    assert_exit_code "$exit_code" 0 "istioctl download-fail"
    assert_not_called "tar_called" "istioctl download-fail" "tar"
}
register_scenario test_istioctl_download_fail

test_istioctl_extract_fail() {
    STUB_CURL_OUTPUT='"tag_name": "1.20.0"'
    STUB_EXTRACT_FAIL=true
    local output exit_code
    output=$(install_istioctl 2>&1); exit_code=$?
    assert_contains "$output" "Failed to extract istioctl from tarball." "istioctl extract-fail"
    assert_exit_code "$exit_code" 0 "istioctl extract-fail"
    assert_not_called "install_called" "istioctl extract-fail" "install"
}
register_scenario test_istioctl_extract_fail

test_istioctl_install_fail() {
    STUB_CURL_OUTPUT='"tag_name": "1.20.0"'
    STUB_INSTALL_FAIL=true
    local output exit_code
    output=$(install_istioctl 2>&1); exit_code=$?
    assert_contains "$output" "Failed to install istioctl." "istioctl install-fail"
    assert_exit_code "$exit_code" 0 "istioctl install-fail"
}
register_scenario test_istioctl_install_fail

test_istioctl_success() {
    STUB_CURL_OUTPUT='"tag_name": "1.20.0"'
    local output exit_code
    output=$(install_istioctl 2>&1); exit_code=$?
    assert_contains "$output" "istioctl installed successfully v1.20.0." "istioctl success"
    assert_exit_code "$exit_code" 0 "istioctl success"
    assert_called "install_called" "istioctl success" "install"
}
register_scenario test_istioctl_success

test_zoom_already_installed() {
    STUB_ALREADY_INSTALLED=true
    local output exit_code
    output=$(install_zoom 2>&1); exit_code=$?
    assert_contains "$output" "already installed. Skipping." "zoom already-installed"
    assert_exit_code "$exit_code" 0 "zoom already-installed"
    assert_not_called "curl_called" "zoom already-installed" "curl"
}
register_scenario test_zoom_already_installed

test_zoom_dry_run() {
    DRY_RUN=true
    local output exit_code
    output=$(install_zoom 2>&1); exit_code=$?
    assert_contains "$output" "[DRY-RUN]" "zoom dry-run"
    assert_exit_code "$exit_code" 0 "zoom dry-run"
    assert_not_called "curl_called" "zoom dry-run" "curl"
}
register_scenario test_zoom_dry_run

test_zoom_download_fail() {
    STUB_DOWNLOAD_FAIL=true
    local output exit_code
    output=$(install_zoom 2>&1); exit_code=$?
    assert_contains "$output" "Failed to download Zoom" "zoom download-fail"
    assert_exit_code "$exit_code" 0 "zoom download-fail"
    assert_not_called "dpkg_called" "zoom download-fail" "dpkg"
}
register_scenario test_zoom_download_fail

test_zoom_install_fail_then_fixed() {
    STUB_DPKG_INSTALL_FAIL=true
    STUB_DPKG_INSTALLED=true
    STUB_DPKG_LIST_NAME="zoom"
    local output exit_code
    output=$(install_zoom 2>&1); exit_code=$?
    assert_contains "$output" "Zoom installed successfully vlatest." "zoom install-fail-then-fixed"
    assert_exit_code "$exit_code" 0 "zoom install-fail-then-fixed"
    assert_called "apt_get_called" "zoom install-fail-then-fixed" "apt-get --fix-broken"
}
register_scenario test_zoom_install_fail_then_fixed

test_zoom_install_permanently_broken() {
    STUB_DPKG_INSTALL_FAIL=true
    STUB_DPKG_INSTALLED=false
    local output exit_code
    output=$(install_zoom 2>&1); exit_code=$?
    assert_contains "$output" "Failed to install Zoom." "zoom install-permanently-broken"
    assert_exit_code "$exit_code" 0 "zoom install-permanently-broken"
}
register_scenario test_zoom_install_permanently_broken

test_zoom_success() {
    local output exit_code
    output=$(install_zoom 2>&1); exit_code=$?
    assert_contains "$output" "Zoom installed successfully vlatest." "zoom success"
    assert_exit_code "$exit_code" 0 "zoom success"
    assert_called "dpkg_called" "zoom success" "dpkg -i"
}
register_scenario test_zoom_success

test_slack_already_installed() {
    STUB_ALREADY_INSTALLED=true
    local output exit_code
    output=$(install_slack 2>&1); exit_code=$?
    assert_contains "$output" "already installed. Skipping." "slack already-installed"
    assert_exit_code "$exit_code" 0 "slack already-installed"
    assert_not_called "curl_called" "slack already-installed" "curl"
}
register_scenario test_slack_already_installed

test_slack_dry_run() {
    DRY_RUN=true
    local output exit_code
    output=$(install_slack 2>&1); exit_code=$?
    assert_contains "$output" "[DRY-RUN]" "slack dry-run"
    assert_exit_code "$exit_code" 0 "slack dry-run"
    assert_not_called "curl_called" "slack dry-run" "curl"
}
register_scenario test_slack_dry_run

test_slack_resolve_fail() {
    STUB_CURL_OUTPUT=""
    local output exit_code
    output=$(install_slack 2>&1); exit_code=$?
    assert_contains "$output" "Failed to resolve Slack download URL." "slack resolve-fail"
    assert_exit_code "$exit_code" 0 "slack resolve-fail"
    assert_not_called "download_called" "slack resolve-fail" "download_with_cache"
}
register_scenario test_slack_resolve_fail

test_slack_download_fail() {
    STUB_CURL_OUTPUT="Version 4.35.0"
    STUB_DOWNLOAD_FAIL=true
    local output exit_code
    output=$(install_slack 2>&1); exit_code=$?
    assert_contains "$output" "Failed to download Slack" "slack download-fail"
    assert_exit_code "$exit_code" 0 "slack download-fail"
    assert_not_called "dpkg_called" "slack download-fail" "dpkg"
}
register_scenario test_slack_download_fail

test_slack_install_fail_then_fixed() {
    STUB_CURL_OUTPUT="Version 4.35.0"
    STUB_DPKG_INSTALL_FAIL=true
    STUB_DPKG_INSTALLED=true
    STUB_DPKG_LIST_NAME="slack-desktop"
    local output exit_code
    output=$(install_slack 2>&1); exit_code=$?
    assert_contains "$output" "Slack installed successfully v4.35.0." "slack install-fail-then-fixed"
    assert_exit_code "$exit_code" 0 "slack install-fail-then-fixed"
    assert_called "apt_get_called" "slack install-fail-then-fixed" "apt-get --fix-broken"
}
register_scenario test_slack_install_fail_then_fixed

test_slack_install_permanently_broken() {
    STUB_CURL_OUTPUT="Version 4.35.0"
    STUB_DPKG_INSTALL_FAIL=true
    STUB_DPKG_INSTALLED=false
    local output exit_code
    output=$(install_slack 2>&1); exit_code=$?
    assert_contains "$output" "Failed to install Slack." "slack install-permanently-broken"
    assert_exit_code "$exit_code" 0 "slack install-permanently-broken"
}
register_scenario test_slack_install_permanently_broken

test_slack_success() {
    STUB_CURL_OUTPUT="Version 4.35.0"
    local output exit_code
    output=$(install_slack 2>&1); exit_code=$?
    assert_contains "$output" "Slack installed successfully v4.35.0." "slack success"
    assert_exit_code "$exit_code" 0 "slack success"
    assert_called "dpkg_called" "slack success" "dpkg -i"
}
register_scenario test_slack_success

test_jetbrains_already_installed() {
    STUB_ALREADY_INSTALLED=true
    local output exit_code
    output=$(install_jetbrains_toolbox 2>&1); exit_code=$?
    assert_contains "$output" "already installed. Skipping." "jetbrains already-installed"
    assert_exit_code "$exit_code" 0 "jetbrains already-installed"
    assert_not_called "curl_called" "jetbrains already-installed" "curl"
}
register_scenario test_jetbrains_already_installed

test_jetbrains_dry_run() {
    DRY_RUN=true
    local output exit_code
    output=$(install_jetbrains_toolbox 2>&1); exit_code=$?
    assert_contains "$output" "[DRY-RUN]" "jetbrains dry-run"
    assert_exit_code "$exit_code" 0 "jetbrains dry-run"
    assert_not_called "curl_called" "jetbrains dry-run" "curl"
}
register_scenario test_jetbrains_dry_run

test_jetbrains_resolve_fail() {
    STUB_CURL_OUTPUT=""
    local output exit_code
    output=$(install_jetbrains_toolbox 2>&1); exit_code=$?
    assert_contains "$output" "Failed to resolve JetBrains Toolbox download URL." "jetbrains resolve-fail"
    assert_exit_code "$exit_code" 0 "jetbrains resolve-fail"
    assert_not_called "download_called" "jetbrains resolve-fail" "download_with_cache"
}
register_scenario test_jetbrains_resolve_fail

test_jetbrains_download_fail() {
    STUB_CURL_OUTPUT='"linux":{"link":"https://example.com/tb.tar.gz"}'
    STUB_DOWNLOAD_FAIL=true
    local output exit_code
    output=$(install_jetbrains_toolbox 2>&1); exit_code=$?
    assert_contains "$output" "Failed to download JetBrains Toolbox" "jetbrains download-fail"
    assert_exit_code "$exit_code" 0 "jetbrains download-fail"
    assert_not_called "tar_called" "jetbrains download-fail" "tar"
}
register_scenario test_jetbrains_download_fail

test_jetbrains_extract_fail() {
    STUB_CURL_OUTPUT='"linux":{"link":"https://example.com/tb.tar.gz"}'
    STUB_EXTRACT_FAIL=true
    local output exit_code
    output=$(install_jetbrains_toolbox 2>&1); exit_code=$?
    assert_contains "$output" "Failed to extract JetBrains Toolbox from tarball." "jetbrains extract-fail"
    assert_exit_code "$exit_code" 0 "jetbrains extract-fail"
    assert_not_called "find_called" "jetbrains extract-fail" "find"
}
register_scenario test_jetbrains_extract_fail

test_jetbrains_find_empty() {
    STUB_CURL_OUTPUT='"linux":{"link":"https://example.com/tb.tar.gz"}'
    STUB_FIND_EMPTY=true
    local output exit_code
    output=$(install_jetbrains_toolbox 2>&1); exit_code=$?
    assert_contains "$output" "Could not find jetbrains-toolbox binary in archive." "jetbrains find-empty"
    assert_exit_code "$exit_code" 0 "jetbrains find-empty"
}
register_scenario test_jetbrains_find_empty

test_jetbrains_success() {
    STUB_CURL_OUTPUT='"linux":{"link":"https://example.com/tb.tar.gz"}'
    mkdir -p "$STUB_DIR/jetbrains-toolbox"
    touch "$STUB_DIR/jetbrains-toolbox/jetbrains-toolbox"
    local output exit_code
    output=$(install_jetbrains_toolbox 2>&1); exit_code=$?
    assert_contains "$output" "JetBrains Toolbox installed successfully." "jetbrains success"
    assert_exit_code "$exit_code" 0 "jetbrains success"
}
register_scenario test_jetbrains_success

test_awscli_already_installed() {
    STUB_ALREADY_INSTALLED=true
    local output exit_code
    output=$(install_awscli 2>&1); exit_code=$?
    assert_contains "$output" "already installed. Skipping." "awscli already-installed"
    assert_exit_code "$exit_code" 0 "awscli already-installed"
    assert_not_called "download_called" "awscli already-installed" "download_with_cache"
}
register_scenario test_awscli_already_installed

test_awscli_dry_run() {
    DRY_RUN=true
    local output exit_code
    output=$(install_awscli 2>&1); exit_code=$?
    assert_contains "$output" "[DRY-RUN]" "awscli dry-run"
    assert_exit_code "$exit_code" 0 "awscli dry-run"
    assert_not_called "download_called" "awscli dry-run" "download_with_cache"
}
register_scenario test_awscli_dry_run

test_awscli_download_fail() {
    STUB_DOWNLOAD_FAIL=true
    local output exit_code
    output=$(install_awscli 2>&1); exit_code=$?
    assert_contains "$output" "Failed to download AWS CLI" "awscli download-fail"
    assert_exit_code "$exit_code" 0 "awscli download-fail"
    assert_not_called "unzip_called" "awscli download-fail" "unzip"
}
register_scenario test_awscli_download_fail

test_awscli_extract_fail() {
    STUB_EXTRACT_FAIL=true
    local output exit_code
    output=$(install_awscli 2>&1); exit_code=$?
    assert_contains "$output" "Failed to extract AWS CLI installer." "awscli extract-fail"
    assert_exit_code "$exit_code" 0 "awscli extract-fail"
    assert_not_called "sudo_called" "awscli extract-fail" "sudo"
}
register_scenario test_awscli_extract_fail

test_awscli_install_fail() {
    mkdir -p "$STUB_DIR/aws"
    cat > "$STUB_DIR/aws/install" <<'EOF'
#!/bin/bash
exit 1
EOF
    chmod +x "$STUB_DIR/aws/install"
    local output exit_code
    output=$(install_awscli 2>&1); exit_code=$?
    assert_contains "$output" "Failed to install AWS CLI." "awscli install-fail"
    assert_exit_code "$exit_code" 0 "awscli install-fail"
}
register_scenario test_awscli_install_fail

test_awscli_success() {
    mkdir -p "$STUB_DIR/aws"
    cat > "$STUB_DIR/aws/install" <<'EOF'
#!/bin/bash
exit 0
EOF
    chmod +x "$STUB_DIR/aws/install"
    local output exit_code
    output=$(install_awscli 2>&1); exit_code=$?
    assert_contains "$output" "AWS CLI installed successfully." "awscli success"
    assert_exit_code "$exit_code" 0 "awscli success"
}
register_scenario test_awscli_success

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
if [ "${#PACKAGES_TO_INSTALL[@]}" -eq 2 ]; then
    PASS_COUNT=$((PASS_COUNT + 1))
else
    FAIL_COUNT=$((FAIL_COUNT + 1))
    FAILURES+=("package-file override: expected 2 deduped packages, got ${#PACKAGES_TO_INSTALL[@]}")
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

echo
echo "Passed: $PASS_COUNT  Failed: $FAIL_COUNT"
if [ "$FAIL_COUNT" -gt 0 ]; then
    printf 'FAILURES:\n'
    printf '  - %s\n' "${FAILURES[@]}"
    exit 1
fi
exit 0
