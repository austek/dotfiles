# shellcheck shell=bash
# Sourced by bin/setup.sh — stow orchestration and per-tool dotfiles/profile configuration.

set -euo pipefail

# Stages conflicting paths under $1, outside every stowed tree, keeping each path
# relative to $HOME so restoring is a plain mv.
stage_stow_conflicts() {
    local stage="$1"
    shift
    local simulated conflicts rel home_real parent_real
    home_real=$(realpath -e -- "$HOME") || return 1
    simulated=$(stow --simulate "$@" 2>&1 || true)
    conflicts=$(printf '%s\n' "$simulated" | sed -nE \
        -e 's/^.*existing target is (neither a link nor a directory|not owned by stow): (.+)$/\2/p' \
        -e 's/^.*cannot stow .* over existing target (.+) since .*$/\1/p' | sort -u)
    while IFS= read -r rel; do
        [[ -n "$rel" ]] || continue
        case "$rel" in
            /*|..|../*|*/../*) log_warn "Not backing up suspicious path: $rel"; continue ;;
            *) ;;
        esac
        [[ -e "$HOME/$rel" || -L "$HOME/$rel" ]] || continue
        parent_real=$(realpath -e -- "$HOME/$(dirname -- "$rel")") || continue
        case "$parent_real/" in
            "$home_real/"*) ;;
            *) log_warn "Not backing up path outside HOME: $rel"; continue ;;
        esac
        mkdir -p "$stage/$(dirname "$rel")"
        mv -- "$HOME/$rel" "$stage/$rel"
        log_warn "Stow conflict: backing up ~/$rel"
    done <<< "$conflicts"
}

# Never removes $1 unless every copy step succeeded: it holds the only copy of the originals.
finalize_stow_backup() {
    local stage="$1" backup_dir
    [[ -n "$(ls -A "$stage")" ]] || { rmdir "$stage"; return 0; }
    if ! mkdir -p "$STOW_BACKUP_ROOT"; then
        log_error "Could not create $STOW_BACKUP_ROOT; conflicting files remain staged in $stage."
        return 1
    fi
    if ! backup_dir=$(mktemp -d "$STOW_BACKUP_ROOT/$STOW_BACKUP_STAMP.XXXXXX"); then
        log_error "Could not create a backup directory; conflicting files remain staged in $stage."
        return 1
    fi
    if ! cp -a "$stage/." "$backup_dir/"; then
        log_error "Could not copy the backup to $backup_dir; conflicting files remain staged in $stage."
        return 1
    fi
    rm -rf "$stage"
    log_warn "Backed up conflicting files to $backup_dir"
}

stow_with_backup() {
    local stage=""
    if [[ "$FORCE_STOW" = true ]]; then
        stage=$(mktemp -d "$HOME/.stow-backup.XXXXXX")
        stage_stow_conflicts "$stage" "$@"
    fi
    if ! quiet_run stow "$@"; then
        [[ -z "$stage" ]] || finalize_stow_backup "$stage" || true
        log_error "Stow failed. If files block it, re-run with --force (dotfiles-setup) or --force-stow (setup.sh) to back them up and stow anyway."
        return 1
    fi
    [[ -z "$stage" ]] || finalize_stow_backup "$stage"
}

stow_pkg_is_linked() {
    local root="$1" pkg="$2" target="$3"
    local file rel
    file=$(command find "$root/$pkg" \( -type f -o -type l \) -print -quit 2>/dev/null || true)
    [[ -n "$file" ]] || return 1
    rel="${file#"$root/$pkg/"}"
    [[ -e "$target/$rel" ]] || return 1
    [[ "$(readlink -f "$target/$rel")" == "$(readlink -f "$file")" ]]
}

pkgs_not_yet_linked() {
    local root="$1" target="$2"
    shift 2
    local pkg
    for pkg in "$@"; do
        stow_pkg_is_linked "$root" "$pkg" "$target" || printf '%s\n' "$pkg"
    done
}

configure_dotfiles() {
    log_step "Step 7: Configuring dotfiles..."

    # Perl-regex-escapes a relative path for use in stow's --ignore/--override, whose
    # patterns are otherwise interpreted as regexes (a literal '.' in a filename would
    # match any character).
    stow_regex_escape() {
        local path="$1"
        # shellcheck disable=SC2016  # single-quoted on purpose: this is a literal sed
        # pattern/replacement, not a shell expansion.
        printf '%s' "$path" | sed -e 's/[.[\*^$()+?{}|\\]/\\&/g'
    }

    # Every path the private overlay would override (a file present in both a private
    # package and the same-named public package — e.g. claude/.claude/CLAUDE.md) has to
    # be excluded from the public stow below, or the two fight over it on every rerun:
    # stow_private_to_home's override only clears the conflict once, but the next plain
    # `stow --restow` of the public package tries to reclaim that path right back, since
    # it has no notion that another source dir is now meant to own it.
    local private_override_ignores=()
    if [[ -n "$PRIVATE_ROOT" ]] && [[ -f "$PRIVATE_ROOT/.stow-packages" ]]; then
        local priv_pkg
        while IFS= read -r priv_pkg; do
            [[ -d "$DOTFILES_DIR/$priv_pkg" ]] || continue
            while IFS= read -r -d '' file; do
                local rel="${file#"$PRIVATE_ROOT"/"$priv_pkg"/}"
                if [[ -f "$DOTFILES_DIR/$priv_pkg/$rel" ]]; then
                    private_override_ignores+=("--ignore=$(stow_regex_escape "$rel")")
                fi
            done < <(find "$PRIVATE_ROOT/$priv_pkg" -type f -print0)
        done < <(grep -vE '^\s*#|^\s*$' "$PRIVATE_ROOT/.stow-packages")
    fi

    stow_common_to_home() {
        local stow_file="$DOTFILES_DIR/.stow-packages"
        if [[ ! -f "$stow_file" ]]; then
            log_warn ".stow-packages file not found. Skipping $HOME stow."
            return
        fi

        log_info "Reading $HOME packages from .stow-packages..."
        local packages_to_stow=()
        mapfile -t packages_to_stow < <(grep -vE '^\s*#|^\s*$' "$stow_file")

        if (( ${#packages_to_stow[@]} == 0 )); then
            log_warn "No packages listed in .stow-packages. Skipping."
            return
        fi

        # 'gradle' must stay folded: its .gradle is the live Gradle home (~1.1M cache files).
        # 'claude' is unfolded (unlike most packages, per-file rather than a convenience
        # exception) so a private overlay can also contribute files under it below without
        # two source dirs fighting over one top-level symlink.
        local fold_packages="gradle"
        local folded=() nofold=()
        for pkg in "${packages_to_stow[@]}"; do
            case " $fold_packages " in
                *" $pkg "*) folded+=("$pkg") ;;
                *) nofold+=("$pkg") ;;
            esac
        done

        # Unfolding links each file individually, so a package holding a live cache
        # would plan millions of links and exhaust stow before it writes anything.
        local unfold_limit=1000
        for pkg in "${nofold[@]}"; do
            local file_count
            file_count=$( (find "$DOTFILES_DIR/$pkg" \( -type f -o -type l \) 2>/dev/null || true) \
                | head -n "$((unfold_limit + 1))" | wc -l )
            if (( file_count > unfold_limit )); then
                log_error "Package '$pkg' holds more than $unfold_limit files; refusing to stow it unfolded."
                log_error "Add it to fold_packages in this script, or drop it from .stow-packages."
                exit 1
            fi
        done

        log_info "Stowing common packages to $HOME: ${packages_to_stow[*]}..."
        if [[ "$DRY_RUN" = true ]]; then
            log_dry_run "Would stow (unfolded) to $HOME: ${nofold[*]:-none}"
            log_dry_run "Would stow (folded) to $HOME: ${folded[*]:-none}"
        else
            local newly_stowed=()
            mapfile -t newly_stowed < <(pkgs_not_yet_linked "$DOTFILES_DIR" "$HOME" "${packages_to_stow[@]}")
            cd "$DOTFILES_DIR"
            if (( ${#nofold[@]} > 0 )); then
                stow_with_backup --restow --no-folding "${private_override_ignores[@]}" --target="$HOME" --verbose=1 "${nofold[@]}"
            fi
            if (( ${#folded[@]} > 0 )); then
                stow_with_backup --restow "${private_override_ignores[@]}" --target="$HOME" --verbose=1 "${folded[@]}"
            fi
            cd "$HOME"
            for pkg in "${newly_stowed[@]}"; do
                [[ -n "$pkg" ]] && track_change "STOW_HOME:$pkg"
            done
            log_success "All $HOME packages stowed."
        fi
    }

    # Layers private files from the optional ~/.dotfiles-private overlay on top of the
    # public stow above — both files the public repo doesn't have at all (e.g. Collibra
    # skills) and files that override a public one at the same path (e.g. a CLAUDE.md
    # with org-specific instructions this machine's user isn't free to publish). The
    # private repo's own .stow-packages says which of its packages carry such files —
    # today that's 'claude' and 'local'. Always unfolded: the private repo distributes
    # a handful of files, never a bulk cache dir, so the fold/unfold split above doesn't
    # apply here.
    clear_public_symlink_at_private_path() {
        local pkg="$1" file="$2"
        local rel="${file#"$PRIVATE_ROOT"/"$pkg"/}"
        local target="$HOME/$rel"
        [[ -L "$target" ]] || return 0
        # stow --override only reclaims a file not owned by ANY package; it can't make one
        # source dir win over a symlink stow already placed from a *different* source dir
        # (it just sees "existing target is not owned by stow" and refuses either way). So
        # a private file that's meant to replace a public one at the same path — not just
        # add alongside it — has to have that public symlink cleared first, by hand, here.
        local link_target
        link_target=$(readlink -f "$target")
        case "$link_target" in
            "$DOTFILES_DIR"/*) rm -f -- "$target" ;;
            *) ;;
        esac
    }

    stow_private_to_home() {
        if [[ -z "$PRIVATE_ROOT" ]]; then
            return
        fi
        local private_stow_file="$PRIVATE_ROOT/.stow-packages"
        if [[ ! -f "$private_stow_file" ]]; then
            log_info "No .stow-packages in the private overlay ($PRIVATE_ROOT). Skipping private stow."
            return
        fi

        local private_packages=()
        mapfile -t private_packages < <(grep -vE '^\s*#|^\s*$' "$private_stow_file")
        if (( ${#private_packages[@]} == 0 )); then
            return
        fi

        log_info "Stowing private-overlay packages to $HOME: ${private_packages[*]}..."
        if [[ "$DRY_RUN" = true ]]; then
            log_dry_run "Would stow (unfolded, from $PRIVATE_ROOT, overriding any public file at the same path) to $HOME: ${private_packages[*]}"
        else
            local newly_stowed_private=()
            mapfile -t newly_stowed_private < <(pkgs_not_yet_linked "$PRIVATE_ROOT" "$HOME" "${private_packages[@]}")
            for pkg in "${private_packages[@]}"; do
                while IFS= read -r -d '' file; do
                    clear_public_symlink_at_private_path "$pkg" "$file"
                done < <(find "$PRIVATE_ROOT/$pkg" -type f -print0)
            done
            cd "$PRIVATE_ROOT"
            stow_with_backup --restow --no-folding --target="$HOME" --verbose=1 "${private_packages[@]}"
            cd "$HOME"
            for pkg in "${newly_stowed_private[@]}"; do
                [[ -n "$pkg" ]] && track_change "STOW_PRIVATE:$pkg"
            done
            log_success "All private-overlay packages stowed."
        fi
    }

    stow_common_to_home
    stow_private_to_home

    log_info "Configuring pre-commit git hooks..."
    if [[ "$DRY_RUN" = true ]]; then
        log_dry_run "Would set core.hooksPath to .githooks"
    else
        cd "$DOTFILES_DIR"
        git config --local core.hooksPath .githooks
        log_success "Git hooks path set to .githooks."
    fi
}

configure_claude_profile() {
    log_step "Step 7b: Configuring Claude Code profiles..."

    local profile_dir="${CLAUDE_PROFILE_DIR_OVERRIDE:-$DOTFILES_DIR/claude-profiles}"
    local work_settings="$profile_dir/claude_work.json"
    local personal_settings="$profile_dir/claude_personal.json"
    local homelab_settings="$profile_dir/claude_homelab.json"
    local burst_settings="$profile_dir/claude_burst.json"
    local target="$HOME/.zshrc.profile"
    local wrapper_dir="$HOME/bin"
    local wrapper="$wrapper_dir/claude"
    # Must sort after /usr/lib/environment.d/99-environment.conf, which sets an absolute
    # PATH — environment.d merges by filename across dirs and the last file wins.
    local env_file="$HOME/.config/environment.d/zz-claude-profile.conf"
    local active_settings="$personal_settings"
    if [[ "$MACHINE_PRESET" == "work" ]]; then
        active_settings="$work_settings"
    elif [[ "$MACHINE_PRESET" == "homelab" ]]; then
        active_settings="$homelab_settings"
    fi

    if [[ "$DRY_RUN" = true ]]; then
        log_dry_run "Would write Claude work/personal/burst aliases to $target"
        log_dry_run "Would write Claude PATH wrapper to $wrapper"
        log_dry_run "Would write session PATH ordering to $env_file"
        return 0
    fi

    local burst_dir="$HOME/.claude-burst"
    mkdir -p "$burst_dir"

    # Excludes auth: .credentials.json (API/OAuth) and backups/ (timestamped
    # .claude.json copies, which carry oauthAccount/userID). The live
    # ~/.claude.json / ~/.claude-burst/.claude.json is untouched here.
    local excluded_items=(
        .credentials.json
        backups
    )

    local entry item skip excluded
    for entry in "$HOME/.claude"/* "$HOME/.claude"/.[!.]*; do
        [[ -e "$entry" ]] || continue
        item=$(basename "$entry")
        skip=false
        for excluded in "${excluded_items[@]}"; do
            [[ "$item" = "$excluded" ]] && skip=true && break
        done
        [[ "$skip" = true ]] && continue
        ln -sfn "$entry" "$burst_dir/$item"
    done

    {
        echo "# --- Claude Code profiles (generated by setup.sh, do not edit) ---"
        echo "alias claude-work='claude-tmux work claude --settings \"$work_settings\"'"
        echo "alias claude-personal='claude-tmux personal claude --settings \"$personal_settings\"'"
        echo "alias claude-homelab='claude-tmux homelab claude --settings \"$homelab_settings\"'"
        echo "alias claude-burst='claude-tmux burst env CLAUDE_CONFIG_DIR=\"$burst_dir\" claude --settings \"$burst_settings\"'"
        if [[ "$MACHINE_PRESET" == "work" ]]; then
            echo "alias claude='claude-tmux work claude --settings \"$work_settings\"'"
        elif [[ "$MACHINE_PRESET" == "homelab" ]]; then
            echo "alias claude='claude-tmux homelab claude --settings \"$homelab_settings\"'"
        else
            echo "alias claude='claude-tmux personal claude --settings \"$personal_settings\"'"
        fi
        echo "# --- End Claude Code profile ---"
    } > "$target"

    log_success "Claude profile aliases written to $target."

    mkdir -p "$wrapper_dir"
    cat > "$wrapper" <<EOF
#!/bin/sh
# Generated by setup.sh (configure_claude_profile) — do not edit.
# Applies the $MACHINE_PRESET profile to every PATH invocation of claude, not just
# the interactive zsh sessions that read the ~/.zshrc.profile aliases.
self_dir=\$(CDPATH= cd -- "\$(dirname -- "\$0")" && pwd -P)
real=""
IFS=:
for dir in \$PATH; do
    [ -n "\$dir" ] || dir=.
    resolved=\$(CDPATH= cd -- "\$dir" 2>/dev/null && pwd -P) || continue
    [ "\$resolved" != "\$self_dir" ] || continue
    if [ -x "\$resolved/claude" ]; then
        real="\$resolved/claude"
        break
    fi
done
unset IFS

if [ -z "\$real" ]; then
    echo "claude: no claude binary found on PATH beyond the wrapper at \$0" >&2
    exit 127
fi

exec "\$real" --settings "$active_settings" "\$@"
EOF
    chmod +x "$wrapper"

    log_success "Claude PATH wrapper written to $wrapper ($MACHINE_PRESET profile)."

    mkdir -p "$(dirname "$env_file")"
    # The systemd user manager's PATH carries neither dir, so GUI/IDE-launched apps need
    # both: the wrapper first, then the real binary it execs.
    {
        echo "# Generated by setup.sh (configure_claude_profile) — do not edit."
        echo "PATH=$wrapper_dir:$HOME/.local/bin:\${PATH}"
    } > "$env_file"

    log_success "Session PATH ordering written to $env_file."
    log_warn "Log out and back in for $env_file to reach GUI/IDE-launched apps."
}

change_shell() {
    log_step "Step 8: Changing default shell to Zsh..."
    local zsh_path
    zsh_path=$(command -v zsh 2>/dev/null || echo "/usr/bin/zsh")

    if [[ "$SHELL" == "$zsh_path" ]]; then
        log_info "Default shell is already $zsh_path. Skipping."
    elif [[ "$DRY_RUN" = true ]]; then
        log_dry_run "Would change default shell to $zsh_path using chsh"
        log_dry_run "Would require logout/login for changes to take effect"
    else
        if sudo usermod -s "$zsh_path" "$USER"; then
            log_success "Default shell changed to $zsh_path."
            log_warn "You will need to log out and log back in for this change to take effect."
        else
            log_error "Failed to change default shell. Please run 'chsh -s $zsh_path' manually."
        fi
    fi
}

set_default_terminal() {
    log_step "Step 9: Setting default terminal to Ghostty..."

    local ghostty_path
    ghostty_path=$(command -v ghostty 2>/dev/null || echo "")

    if [[ -z "$ghostty_path" ]]; then
        log_warn "Ghostty is not installed. Skipping default terminal configuration."
        return 0
    fi

    local config_dir="${XDG_CONFIG_HOME:-$HOME/.config}"
    local xdg_terminals_list="$config_dir/xdg-terminals.list"
    local ghostty_entry_id="com.mitchellh.ghostty.desktop"

    if [[ "$DRY_RUN" = true ]]; then
        log_dry_run "Would register and set x-terminal-emulator alternative to $ghostty_path"
        log_dry_run "Would set $ghostty_entry_id as the preferred entry in $xdg_terminals_list"
        return 0
    fi

    # Unlike Terminator, Ubuntu's ghostty package ships no postinst script and never
    # registers itself as an x-terminal-emulator alternative, so it must be installed
    # into the group before it can be selected.
    if sudo update-alternatives --install /usr/bin/x-terminal-emulator x-terminal-emulator "$ghostty_path" 50 \
        && sudo update-alternatives --set x-terminal-emulator "$ghostty_path"; then
        log_success "Default terminal set to Ghostty."
    else
        log_error "Failed to set default terminal. Please run 'sudo update-alternatives --config x-terminal-emulator' manually."
    fi

    # GNOME's Ctrl+Alt+T can resolve the terminal via xdg-terminal-exec, which
    # reads $XDG_CURRENT_DESKTOP-prefixed lists before this generic one — Ubuntu's
    # session-migration script seeds those, so they must be patched too.
    mkdir -p "$config_dir"

    local list updated=0
    for list in "$xdg_terminals_list" "$config_dir"/*-xdg-terminals.list; do
        [[ "$list" = "$xdg_terminals_list" ]] || [[ -e "$list" ]] || continue
        local other_entries=""
        [[ -f "$list" ]] && other_entries=$(grep -vFx "$ghostty_entry_id" "$list" || true)
        if printf '%s\n' "$ghostty_entry_id" > "$list" \
            && { [[ -z "$other_entries" ]] || printf '%s\n' "$other_entries" >> "$list"; }; then
            updated=$((updated + 1))
        else
            log_error "Failed to update $list. Please add '$ghostty_entry_id' as its first line manually."
        fi
    done
    if [[ "$updated" -gt 0 ]]; then
        log_success "Ghostty set as preferred terminal in $updated xdg-terminal-exec list(s)."
    fi

    # gsd-media-keys resolves Ctrl+Alt+T through this deprecated dconf key
    # directly, bypassing x-terminal-emulator and xdg-terminal-exec entirely,
    # whenever it holds a non-default override (e.g. left over from a prior
    # terminal choice) — so it must be repointed at Ghostty too.
    if command -v gsettings >/dev/null 2>&1; then
        if gsettings set org.gnome.desktop.default-applications.terminal exec "$ghostty_path" \
            && gsettings set org.gnome.desktop.default-applications.terminal exec-arg "-e"; then
            log_success "Ghostty set as the GNOME Ctrl+Alt+T terminal."
        else
            log_error "Failed to set the GNOME default terminal key. Please run 'gsettings set org.gnome.desktop.default-applications.terminal exec $ghostty_path' manually."
        fi
    fi
}

