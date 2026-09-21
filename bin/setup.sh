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
ROLLBACK_LOG="$HOME/.dotfiles-setup-rollback.log"
SETUP_IN_PROGRESS=false
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
source "$SCRIPT_DIR/lib/installers.sh"
# shellcheck source=/dev/null
source "$SCRIPT_DIR/lib/dotfiles.sh"

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
            --verbosity)
                # Sets VERBOSITY directly rather than accumulating like -v/-vv/-vvv —
                # used by dotfiles-setup to forward its own already-summed -v/-vv/-vvv
                # count in one flag, without reconstructing a letter-flag combination.
                if [[ $# -lt 2 ]]; then
                    log_error "--verbosity requires a value (0-6)."
                    exit 1
                fi
                if ! [[ "$2" =~ ^[0-9]+$ ]] || [[ "$2" -gt 6 ]]; then
                    log_error "--verbosity must be an integer from 0 to 6, got '$2'."
                    exit 1
                fi
                VERBOSITY="$2"
                shift 2
                ;;
            -h|--help)
                echo "Usage: $0 --preset <work|personal|homelab> [OPTIONS]"
                echo ""
                echo "Options:"
                echo "  --preset <work|personal|homelab>   Machine profile to set up (required)"
                echo "  --package-file <path>               Use this pre-resolved package list instead of deriving one from --preset"
                echo "  --claude-profile-dir <path>          Read claude-profiles/*.json from this directory instead of the repo's own"
                echo "  --private-root <path>                Also stow packages listed in this dir's .stow-packages (the private overlay)"
                echo "  --verbosity <0-6>                    Set VERBOSITY directly (what dotfiles-setup passes for -v/-vv/-vvv); prefer -v/-vv/-vvv by hand"
                echo "  --dry-run                   Show what would be done without executing commands"
                echo "  -v, --verbose               Show step-by-step progress (INFO/SUCCESS messages)"
                echo "  -vv                         Also show raw output from apt/stow/dpkg/etc."
                echo "  -vvv                        Full debug: also enable bash trace (set -x)"
                echo "  -h, --help                  Show this help message"
                exit 0
                ;;
            *)
                log_error "Unknown option: $1"
                echo "Use --help for usage information"
                exit 1
                ;;
        esac
    done

    validate_machine_preset

    if [[ "$VERBOSITY" -ge 3 ]]; then
        set -x
    fi

    if [[ "$DRY_RUN" = true ]]; then
        log_warn "=== DRY-RUN MODE: No changes will be made ==="
    fi

    log_step "Starting Ubuntu Dotfiles Setup..."

    if [[ "$EUID" -eq 0 ]]; then
        log_error "This script must not be run as root. Use 'sudo' when prompted."
        exit 1
    fi

    if [[ ! -d "$DOTFILES_DIR" ]]; then
        log_error "Dotfiles directory not found at $DOTFILES_DIR. Please clone it first."
        exit 1
    fi
    cd "$DOTFILES_DIR"

    if [[ "$DRY_RUN" = false ]]; then
        SETUP_IN_PROGRESS=true
        : > "$ROLLBACK_LOG"
        log_info "Rollback tracking enabled. Log: $ROLLBACK_LOG"
    fi

    prompt_sudo
    determine_packages_to_install

    install_core_deps
    disable_snapd
    strip_snap_from_system_path
    configure_apt_sources
    install_packages
    enable_gpaste_extension
    install_github_bins
    configure_docker_group
    configure_dotfiles
    configure_claude_profile
    configure_rtk_cli
    configure_cozempic_cli
    configure_serena
    configure_caveman_proxy
    change_shell
    set_default_terminal

    SETUP_IN_PROGRESS=false

    echo
    log_banner "----------------------------------------------------"
    if [[ "$DRY_RUN" = true ]]; then
        log_banner "Dry-run complete! No changes were made."
        log_banner "Run without --dry-run to execute the setup."
    else
        log_banner "Setup complete!"
        log_banner "Please log out and log back in for all changes (especially the new shell) to apply."
        log_banner "Don't forget to manually add any secrets to ~/.zshrc.secret"
        log_banner "For Claude Code to control Chrome, install the 'Claude' extension from the Chrome Web Store and run 'claude --chrome' once to complete onboarding (this pairing is per-machine and can't be scripted)."
    fi
    log_banner "----------------------------------------------------"
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    main "$@"
fi
