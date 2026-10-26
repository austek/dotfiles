#!/bin/bash

# shellcheck disable=SC2034  # globals below are consumed by the sourced bin/lib/*.sh files
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
DOTFILES_DIR=$(dirname "$SCRIPT_DIR")
APT_PACKAGE_DIR="$DOTFILES_DIR/packages"
PACKAGES_TO_INSTALL=()
SUDO_REFRESH_PID=""
DRY_RUN=false
VERBOSITY=0
MACHINE_PRESET=""
PACKAGE_FILE_OVERRIDE=""
CLAUDE_PROFILE_DIR_OVERRIDE=""
PRIVATE_ROOT=""
NO_BANNER=false
NO_HEADER=false
BANNER_ONLY=false
ROLLBACK_LOG="$HOME/.dotfiles-setup-rollback.log"
SETUP_IN_PROGRESS=false
KEEP_ROLLBACK_LOG=false
TEMP_DIRS_TO_CLEAN=()

COLOR_RESET='\033[0m'
COLOR_GREEN='\033[0;32m'
COLOR_YELLOW='\033[0;33m'
COLOR_CYAN='\033[0;36m'
COLOR_RED='\033[0;31m'

# shellcheck source=/dev/null
source "$SCRIPT_DIR/lib/log.sh"
# shellcheck source=/dev/null
source "$SCRIPT_DIR/lib/rollback.sh"
# shellcheck source=/dev/null
source "$SCRIPT_DIR/lib/helpers.sh"
# shellcheck source=/dev/null
source "$SCRIPT_DIR/lib/apt.sh"
# shellcheck source=/dev/null
source "$SCRIPT_DIR/lib/dotfiles.sh"

SETUP_STEPS=(
    install_core_deps disable_snapd strip_snap_from_system_path configure_apt_sources
    install_packages enable_gpaste_extension install_github_bins configure_docker_group
    configure_claude_profile change_shell set_default_terminal
)
ONLY_STEPS=()

step_selected() {
    local step="$1"
    (( ${#ONLY_STEPS[@]} == 0 )) && return 0
    array_contains "$step" "${ONLY_STEPS[@]}"
}

validate_only_steps() {
    local name
    for name in "${ONLY_STEPS[@]:-}"; do
        [[ -z "$name" ]] && continue
        if ! array_contains "$name" "${SETUP_STEPS[@]}"; then
            log_error "Unknown step in --only: '$name'. See --list-steps."
            exit 1
        fi
    done
}

print_completion_banner() {
    echo
    log_banner "----------------------------------------------------"
    if [[ "$DRY_RUN" = true ]]; then
        log_banner "Dry-run complete! No changes were made."
        log_banner "Run without --dry-run to execute the setup."
    else
        log_banner "Setup complete!"
        log_banner "Please log out and log back in for all changes (especially the new shell) to apply."
        log_banner "Don't forget to manually add any secrets to ~/.config/dotfiles/secrets.env"
        log_banner "For Claude Code to control Chrome, install the 'Claude' extension from the Chrome Web Store and run 'claude --chrome' once to complete onboarding (this pairing is per-machine and can't be scripted)."
    fi
    log_banner "----------------------------------------------------"
}

usage() {
    cat <<EOF
Usage: $0 --preset <name> --package-file <path> [OPTIONS]

Options:
  --preset <name>                    Machine profile to set up (required)
  --package-file <path>               Pre-resolved package list (required; dotfiles-setup resolves it from the preset)
  --claude-profile-dir <path>          Read claude-profiles/*.json from this directory instead of the repo's own
  --private-root <path>                Also stow packages listed in this dir's .stow-packages (the private overlay)
  --verbosity <0-6>                    Set VERBOSITY directly (what dotfiles-setup passes for -v/-vv/-vvv); prefer -v/-vv/-vvv by hand
  --no-banner                          Skip the completion banner (dotfiles-setup prints it after its own steps)
  --no-header                          Skip the start-up header and dry-run notice (dotfiles-setup prints them first)
  --banner-only                        Print the completion banner and exit
  --only <step[,step...]>              Run only these steps (see --list-steps); a run without the first step keeps the earlier rollback log, one without the last keeps it afterwards
  --list-steps                         Print the step names in run order and exit
  --dry-run                   Show what would be done without executing commands
  -v, --verbose               Show step-by-step progress (INFO/SUCCESS messages)
  -vv                         Also show raw output from apt/stow/dpkg/etc.
  -vvv                        Full debug: also enable bash trace (set -x)
  -h, --help                  Show this help message
EOF
}

main() {
    while [[ $# -gt 0 ]]; do
        case $1 in
            --dry-run)
                DRY_RUN=true
                shift
                ;;
            -v|--verbose)
                VERBOSITY=$((VERBOSITY + 1))
                shift
                ;;
            -vv)
                VERBOSITY=$((VERBOSITY + 2))
                shift
                ;;
            -vvv)
                VERBOSITY=$((VERBOSITY + 3))
                shift
                ;;
            --preset)
                if [[ $# -lt 2 ]]; then
                    log_error "--preset requires a value ('work', 'personal', or 'homelab')."
                    exit 1
                fi
                MACHINE_PRESET="$2"
                shift 2
                ;;
            --package-file)
                if [[ $# -lt 2 ]]; then
                    log_error "--package-file requires a path."
                    exit 1
                fi
                PACKAGE_FILE_OVERRIDE="$2"
                shift 2
                ;;
            --claude-profile-dir)
                if [[ $# -lt 2 ]]; then
                    log_error "--claude-profile-dir requires a path."
                    exit 1
                fi
                CLAUDE_PROFILE_DIR_OVERRIDE="$2"
                shift 2
                ;;
            --private-root)
                if [[ $# -lt 2 ]]; then
                    log_error "--private-root requires a path."
                    exit 1
                fi
                PRIVATE_ROOT="$2"
                shift 2
                ;;
            --no-banner)
                NO_BANNER=true
                shift
                ;;
            --no-header)
                NO_HEADER=true
                shift
                ;;
            --banner-only)
                BANNER_ONLY=true
                shift
                ;;
            --list-steps)
                printf '%s\n' "${SETUP_STEPS[@]}"
                exit 0
                ;;
            --only)
                if [[ $# -lt 2 ]]; then
                    log_error "--only requires a comma-separated list of step names."
                    exit 1
                fi
                local only_arg="$2"
                IFS=',' read -r -a ONLY_STEPS <<< "$only_arg"
                shift 2
                ;;
            --verbosity)
                # Sets VERBOSITY directly rather than accumulating like -v/-vv/-vvv —
                # used by dotfiles-setup to forward its own already-summed -v/-vv/-vvv
                # count in one flag, without reconstructing a letter-flag combination.
                if [[ $# -lt 2 ]]; then
                    log_error "--verbosity requires a value (0-6)."
                    exit 1
                fi
                local verbosity_arg="$2"
                if ! [[ "$verbosity_arg" =~ ^[0-9]+$ ]] || [[ "$verbosity_arg" -gt 6 ]]; then
                    log_error "--verbosity must be an integer from 0 to 6, got '$verbosity_arg'."
                    exit 1
                fi
                VERBOSITY="$verbosity_arg"
                shift 2
                ;;
            -h|--help)
                usage "$0"
                exit 0
                ;;
            *)
                local unknown_option="$1"
                log_error "Unknown option: $unknown_option"
                echo "Use --help for usage information"
                exit 1
                ;;
        esac
    done

    if [[ "$BANNER_ONLY" = true ]]; then
        print_completion_banner
        exit 0
    fi

    validate_machine_preset
    validate_only_steps

    if [[ "$VERBOSITY" -ge 3 ]]; then
        set -x
    fi

    if [[ "$NO_HEADER" = false ]]; then
        if [[ "$DRY_RUN" = true ]]; then
            log_warn "=== DRY-RUN MODE: No changes will be made ==="
        fi
        log_step "Starting Ubuntu Dotfiles Setup..."
    fi

    if [[ "$EUID" -eq 0 ]]; then
        log_error "This script must not be run as root. Use 'sudo' when prompted."
        exit 1
    fi

    if [[ ! -d "$DOTFILES_DIR" ]]; then
        log_error "Dotfiles directory not found at $DOTFILES_DIR. Please clone it first."
        exit 1
    fi
    [[ -z "${PACKAGE_FILE_OVERRIDE:-}" ]] || PACKAGE_FILE_OVERRIDE=$(realpath -m -- "$PACKAGE_FILE_OVERRIDE")
    [[ -z "${CLAUDE_PROFILE_DIR_OVERRIDE:-}" ]] || CLAUDE_PROFILE_DIR_OVERRIDE=$(realpath -m -- "$CLAUDE_PROFILE_DIR_OVERRIDE")
    [[ -z "${PRIVATE_ROOT:-}" ]] || PRIVATE_ROOT=$(realpath -m -- "$PRIVATE_ROOT")
    cd "$DOTFILES_DIR"

    if [[ "$DRY_RUN" = false ]]; then
        SETUP_IN_PROGRESS=true
        step_selected "${SETUP_STEPS[0]}" && : > "$ROLLBACK_LOG"
        step_selected "${SETUP_STEPS[-1]}" || KEEP_ROLLBACK_LOG=true
        log_info "Rollback tracking enabled. Log: $ROLLBACK_LOG"
    fi

    prompt_sudo
    determine_packages_to_install

    local step
    for step in "${SETUP_STEPS[@]}"; do
        if step_selected "$step"; then
            "$step"
        fi
    done

    SETUP_IN_PROGRESS=false

    if [[ "$NO_BANNER" = false ]]; then
        print_completion_banner
    fi
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    main "$@"
fi
