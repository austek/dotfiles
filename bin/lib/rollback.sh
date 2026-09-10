# shellcheck shell=bash
# Sourced by bin/setup.sh — rollback tracking, temp-dir registry, and the EXIT-trap cleanup handler.

set -euo pipefail

track_change() {
    if [ "$DRY_RUN" = false ] && [ "$SETUP_IN_PROGRESS" = true ]; then
        echo "$1" >> "$ROLLBACK_LOG"
    fi
}

# Registers a mktemp -d directory for cleanup in the EXIT trap below, so it's
# removed even if `set -e` aborts the script mid-function (a `trap ... RETURN`
# alone does not fire on an errexit-triggered abort, only on normal return).
register_temp_dir() {
    TEMP_DIRS_TO_CLEAN+=("$1")
}

perform_rollback() {
    if [ ! -f "$ROLLBACK_LOG" ] || [ ! -s "$ROLLBACK_LOG" ]; then
        log_info "No rollback log found. Nothing to roll back."
        return 0
    fi

    log_warn "=========================================="
    log_warn "Setup failed. Rolling back changes..."
    log_warn "=========================================="

    local rollback_commands=()
    while IFS= read -r line; do
        rollback_commands=("$line" "${rollback_commands[@]}")
    done < "$ROLLBACK_LOG"

    for cmd in "${rollback_commands[@]}"; do
        local action="${cmd%%:*}"
        local data="${cmd#*:}"

        case "$action" in
            STOW_HOME)
                log_info "Unstowing package from HOME: $data"
                cd "$DOTFILES_DIR"
                stow --delete --target="$HOME" "$data" 2>/dev/null || log_warn "Failed to unstow $data"
                cd "$HOME"
                ;;
            STOW_ROOT)
                log_info "Unstowing package from /: $data"
                cd "$DOTFILES_DIR"
                sudo stow --delete --target=/ "$data" 2>/dev/null || log_warn "Failed to unstow $data"
                cd "$HOME"
                ;;
            DOCKER_GROUP)
                log_info "Removing user from docker group"
                sudo gpasswd -d "$USER" docker 2>/dev/null || log_warn "Failed to remove user from docker group"
                ;;
            FILE_BACKUP)
                local backup_file="${data%.backup-*}"
                if [ -f "$data" ]; then
                    log_info "Restoring backed up file: $backup_file"
                    sudo mv "$data" "$backup_file" 2>/dev/null || log_warn "Failed to restore $backup_file"
                fi
                ;;
            FILE_CREATED)
                log_info "Removing generated file: $data"
                sudo rm -f "$data" 2>/dev/null || log_warn "Failed to remove $data"
                ;;
            *)
                log_warn "Unknown rollback action: $action"
                ;;
        esac
    done

    log_success "Rollback completed."
    log_info "Removing rollback log..."
    rm -f "$ROLLBACK_LOG"

    log_warn "Note: Installed packages (apt, snap) were NOT removed during rollback."
    log_warn "You may want to remove them manually if needed."
}

cleanup() {
    local exit_code=$?

    local temp_dir
    for temp_dir in "${TEMP_DIRS_TO_CLEAN[@]:-}"; do
        [ -n "$temp_dir" ] && rm -rf -- "$temp_dir"
    done

    if [ -n "$SUDO_REFRESH_PID" ] && kill -0 "$SUDO_REFRESH_PID" 2>/dev/null; then
        kill "$SUDO_REFRESH_PID" 2>/dev/null || true
    fi

    if [ $exit_code -ne 0 ] && [ "$SETUP_IN_PROGRESS" = true ]; then
        local line_number=$1
        log_error "Script exited with error code $exit_code on line ${line_number}."

        if [ -f "$ROLLBACK_LOG" ] && [ -s "$ROLLBACK_LOG" ]; then
            echo ""
            log_warn "Setup did not complete successfully."
            log_warn "A rollback log has been created at: $ROLLBACK_LOG"

            if [ -t 0 ]; then
                read -rp "Do you want to roll back changes? (y/N): " rollback_choice
                case $rollback_choice in
                    [Yy]* )
                        perform_rollback
                        ;;
                    * )
                        log_info "Rollback skipped. You can manually roll back later by running:"
                        log_info "  source $SCRIPT_DIR/setup.sh && perform_rollback"
                        ;;
                esac
            else
                log_info "Non-interactive mode: Skipping rollback prompt."
                log_info "You can manually roll back by reviewing: $ROLLBACK_LOG"
            fi
        fi
    elif [ $exit_code -eq 0 ] && [ -f "$ROLLBACK_LOG" ]; then
        rm -f "$ROLLBACK_LOG"
    fi
}
trap 'cleanup $LINENO' EXIT

