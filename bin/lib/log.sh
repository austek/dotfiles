# shellcheck shell=bash
# Sourced by bin/setup.sh — logging/output primitives shared by every other lib file.

set -euo pipefail

# INFO/SUCCESS are step narration — hidden by default, shown at -v and up.
# WARNING/ERROR/DRY-RUN are actionable and always shown regardless of verbosity.
log_info() {
    [ "$VERBOSITY" -ge 1 ] || return 0
    echo -e "${COLOR_CYAN}[INFO] $1${COLOR_RESET}"
}

log_success() {
    [ "$VERBOSITY" -ge 1 ] || return 0
    echo -e "${COLOR_GREEN}[SUCCESS] $1${COLOR_RESET}"
}

# Used for the completion banner.
log_banner() {
    echo -e "${COLOR_GREEN}[SUCCESS] $1${COLOR_RESET}"
}

# Always shown, independent of verbosity — marks a top-level step so the
# script never goes silent for the length of a step, even at default -v 0.
log_step() {
    echo -e "${COLOR_CYAN}==> $1${COLOR_RESET}"
}

log_warn() {
    echo -e "${COLOR_YELLOW}[WARNING] $1${COLOR_RESET}"
}

log_error() {
    echo -e "${COLOR_RED}[ERROR] $1${COLOR_RESET}" >&2
}

log_dry_run() {
    if [ "$DRY_RUN" = true ]; then
        echo -e "${COLOR_YELLOW}[DRY-RUN] $1${COLOR_RESET}"
        return 0
    fi
    return 1
}

# Runs "$@", suppressing its combined output unless -vv+ is set — failures
# always surface the captured output first, regardless of verbosity, so
# nothing is lost, only hidden on the happy path.
quiet_run() {
    if [ "$VERBOSITY" -ge 2 ]; then
        "$@"
        return $?
    fi
    local output status
    # Assigned via `if` rather than a bare `output=$(...)`: under `set -e`, a
    # bare assignment aborts the script the instant "$@" fails, before
    # `status=$?` ever runs -- skipping the captured-output print below entirely.
    if output=$("$@" 2>&1); then
        status=0
    else
        status=$?
    fi
    if [ $status -ne 0 ]; then
        printf '%s\n' "$output" >&2
    fi
    return $status
}

