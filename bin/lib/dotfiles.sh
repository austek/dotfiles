# shellcheck shell=bash
# Sourced by bin/setup.sh — stow orchestration and per-tool dotfiles/profile configuration.

set -euo pipefail

configure_dotfiles() {
    log_step "Step 7: Configuring dotfiles..."

    stow_common_to_home() {
        local stow_file="$DOTFILES_DIR/.stow-packages"
        if [ ! -f "$stow_file" ]; then
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
        if [ "$DRY_RUN" = true ]; then
            log_dry_run "Would stow (unfolded) to $HOME: ${nofold[*]:-none}"
            log_dry_run "Would stow (folded) to $HOME: ${folded[*]:-none}"
        else
            cd "$DOTFILES_DIR"
            if (( ${#nofold[@]} > 0 )); then
                quiet_run stow --restow --no-folding --target="$HOME" --verbose=1 "${nofold[@]}"
            fi
            if (( ${#folded[@]} > 0 )); then
                quiet_run stow --restow --target="$HOME" --verbose=1 "${folded[@]}"
            fi
            cd "$HOME"
            for pkg in "${packages_to_stow[@]}"; do
                track_change "STOW_HOME:$pkg"
            done
            log_success "All $HOME packages stowed."
        fi
    }

    # Layers private-only files (e.g. Collibra-specific Claude skills or scripts) from
    # the optional ~/.dotfiles-private overlay on top of the public stow above. The
    # private repo's own .stow-packages says which of its packages carry such files —
    # today that's 'claude' and 'local'. Always unfolded: the private repo distributes
    # a handful of files, never a bulk cache dir, so the fold/unfold split above doesn't
    # apply here.
    stow_private_to_home() {
        if [ -z "$PRIVATE_ROOT" ]; then
            return
        fi
        local private_stow_file="$PRIVATE_ROOT/.stow-packages"
        if [ ! -f "$private_stow_file" ]; then
            log_info "No .stow-packages in the private overlay ($PRIVATE_ROOT). Skipping private stow."
            return
        fi

        local private_packages=()
        mapfile -t private_packages < <(grep -vE '^\s*#|^\s*$' "$private_stow_file")
        if (( ${#private_packages[@]} == 0 )); then
            return
        fi

        log_info "Stowing private-overlay packages to $HOME: ${private_packages[*]}..."
        if [ "$DRY_RUN" = true ]; then
            log_dry_run "Would stow (unfolded, from $PRIVATE_ROOT) to $HOME: ${private_packages[*]}"
        else
            cd "$PRIVATE_ROOT"
            quiet_run stow --restow --no-folding --target="$HOME" --verbose=1 "${private_packages[@]}"
            cd "$HOME"
            for pkg in "${private_packages[@]}"; do
                track_change "STOW_PRIVATE:$pkg"
            done
            log_success "All private-overlay packages stowed."
        fi
    }

    stow_common_to_home
    stow_private_to_home

    log_info "Configuring pre-commit git hooks..."
    if [ "$DRY_RUN" = true ]; then
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
    if [ "$MACHINE_PRESET" == "work" ]; then
        active_settings="$work_settings"
    elif [ "$MACHINE_PRESET" == "homelab" ]; then
        active_settings="$homelab_settings"
    fi

    if [ "$DRY_RUN" = true ]; then
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
        [ -e "$entry" ] || continue
        item=$(basename "$entry")
        skip=false
        for excluded in "${excluded_items[@]}"; do
            [ "$item" = "$excluded" ] && skip=true && break
        done
        [ "$skip" = true ] && continue
        ln -sfn "$entry" "$burst_dir/$item"
    done

    {
        echo "# --- Claude Code profiles (generated by setup.sh, do not edit) ---"
        echo "alias claude-work='claude --settings \"$work_settings\"'"
        echo "alias claude-personal='claude --settings \"$personal_settings\"'"
        echo "alias claude-homelab='claude --settings \"$homelab_settings\"'"
        echo "alias claude-burst='CLAUDE_CONFIG_DIR=\"$burst_dir\" claude --settings \"$burst_settings\"'"
        if [ "$MACHINE_PRESET" == "work" ]; then
            echo "alias claude='claude --settings \"$work_settings\"'"
        elif [ "$MACHINE_PRESET" == "homelab" ]; then
            echo "alias claude='claude --settings \"$homelab_settings\"'"
        else
            echo "alias claude='claude --settings \"$personal_settings\"'"
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

# claude/.claude/settings.json's Bash PreToolUse hook runs bare `rtk hook
# claude` with no `|| true` fallback — every Bash tool call breaks without
# it. Not an apt package, so it can't go through packages/*.txt like the rest.
configure_rtk_cli() {
    log_step "Step 7c: Verifying the rtk CLI is installed..."

    if command_exists rtk; then
        log_success "rtk CLI already installed ($(rtk --version 2>/dev/null))."
        return
    fi

    if [ "$DRY_RUN" = true ]; then
        log_dry_run "Would install the rtk CLI via https://github.com/rtk-ai/rtk's install script."
        return
    fi

    log_info "rtk CLI not found; installing..."
    if curl -fsSL "https://raw.githubusercontent.com/rtk-ai/rtk/refs/heads/master/install.sh" | sh; then
        log_success "rtk CLI installed ($(command_exists rtk && rtk --version 2>/dev/null))."
    else
        log_error "Failed to install rtk. Install it manually: curl -fsSL https://raw.githubusercontent.com/rtk-ai/rtk/refs/heads/master/install.sh | sh"
    fi
}

# claude/.claude/settings.json wires cozempic into Claude Code's hooks, but
# the standalone `cozempic` CLI those hooks shell out to is a pip package
# Claude Code never installs — without it, every hook silently no-ops.
configure_cozempic_cli() {
    log_step "Step 7d: Verifying the cozempic CLI is installed..."

    if command_exists cozempic; then
        log_success "cozempic CLI already installed ($(cozempic --version 2>/dev/null))."
        return
    fi

    if [ "$DRY_RUN" = true ]; then
        log_dry_run "Would install the cozempic CLI via pipx."
        return
    fi

    # Debian/Ubuntu's Python is PEP 668 externally-managed, so plain pip/uv
    # --user installs are refused. pipx sidesteps that via its own venv, which
    # matches claude/.claude/settings.json's hardcoded pipx venv path fallback.
    if ! command_exists pipx; then
        log_error "pipx not found; can't install cozempic. Add 'pipx' to packages/apt_common.txt and re-run, or install manually: pipx install cozempic"
        return
    fi

    log_info "cozempic CLI not found; installing..."
    if pipx install --quiet cozempic; then
        :
    else
        log_error "Failed to install cozempic via pipx. Install it manually: pipx install cozempic"
        return
    fi

    if PATH="$HOME/.local/bin:$PATH" command_exists cozempic; then
        log_success "cozempic CLI installed ($(PATH="$HOME/.local/bin:$PATH" cozempic --version 2>/dev/null))."
    else
        log_warn "cozempic installed but not found on PATH yet; it will resolve once ~/.local/bin is sourced (log out/in or restart your shell)."
    fi
}

# Serena (github.com/oraios/serena) is the MCP server backing Java symbol
# navigation for dgc-core. It's only relevant on work/personal boxes (dgc-core
# checkouts), so this is a no-op on homelab. claude/.claude/settings.json's
# serena-hooks activate/remind commands and the mcp__serena__* permission are
# useless without: pipx installed, the MCP server registered, and — on
# dgc-core's Gradle 9 — a patch to JDT LS's bundled apt/init.gradle trigger.
# The patch lives inside the pipx venv, so `pipx upgrade serena-agent`
# silently wipes it; re-applying it is idempotent, so this step always checks.
configure_serena() {
    log_step "Step 7e: Verifying Serena MCP is installed and configured..."

    if [ "$MACHINE_PRESET" == "homelab" ]; then
        log_success "Serena not needed on the homelab profile; skipping."
        return
    fi

    if ! command_exists pipx; then
        log_error "pipx not found; can't install Serena. Add 'pipx' to packages/apt_common.txt and re-run, or install manually: pipx install --python 3.13 serena-agent --pip-args=\"--pre\""
        return
    fi

    if command_exists serena; then
        log_success "Serena CLI already installed ($(serena --version 2>/dev/null | head -n1))."
    elif [ "$DRY_RUN" = true ]; then
        log_dry_run "Would install Serena via: pipx install --python 3.13 serena-agent --pip-args=\"--pre\""
    else
        log_info "Serena CLI not found; installing..."
        if pipx install --python 3.13 serena-agent --pip-args="--pre"; then
            log_success "Serena CLI installed."
        else
            log_error "Failed to install serena-agent via pipx. Install it manually: pipx install --python 3.13 serena-agent --pip-args=\"--pre\""
            return
        fi
    fi

    if [ -f "$HOME/.serena/serena_config.yml" ]; then
        log_success "Serena already initialised ($HOME/.serena/serena_config.yml exists)."
    elif [ "$DRY_RUN" = true ]; then
        log_dry_run "Would run 'serena init'."
    else
        serena init
    fi

    if command_exists claude && claude mcp get serena >/dev/null 2>&1; then
        log_success "Serena already registered as a Claude Code MCP server."
    elif [ "$DRY_RUN" = true ]; then
        log_dry_run "Would run: claude mcp add --scope user serena -- serena start-mcp-server --context claude-code --project-from-cwd"
    elif command_exists claude; then
        claude mcp add --scope user serena -- serena start-mcp-server --context claude-code --project-from-cwd
    else
        log_warn "claude CLI not found; skipping Serena MCP registration."
    fi

    local jdtls_file
    jdtls_file=$(find "$HOME/.local/share/pipx/venvs/serena-agent" -path '*/solidlsp/language_servers/eclipse_jdtls.py' 2>/dev/null | head -n1 || true)

    if [ -z "$jdtls_file" ]; then
        log_warn "eclipse_jdtls.py not found under the serena-agent pipx venv; skipping the Gradle 9 annotation-processing patch."
        return
    fi

    if grep -q '"annotationProcessing": {"enabled": False}' "$jdtls_file"; then
        log_success "Gradle 9 annotation-processing patch already applied to $jdtls_file."
    elif [ "$DRY_RUN" = true ]; then
        log_dry_run "Would patch $jdtls_file: annotationProcessing enabled True -> False (Gradle 9 workaround, see serena#1510)."
    else
        sed -i.bak 's/"annotationProcessing": {"enabled": True}/"annotationProcessing": {"enabled": False}/' "$jdtls_file"
        if grep -q '"annotationProcessing": {"enabled": False}' "$jdtls_file"; then
            log_success "Applied the Gradle 9 annotation-processing patch to $jdtls_file."
        else
            log_error "Failed to patch $jdtls_file. Check it manually against serena#1510."
        fi
    fi
}

# Installs the caveman-ai proxy CLI + engine only. Deliberately skips
# `caveman enable claude`: it rewrites Claude Code's hooks/statusline,
# which would clobber claude/.claude/settings.json's hand-tuned hooks.
configure_caveman_proxy() {
    log_step "Step 7f: Verifying the caveman proxy CLI is installed..."

    if ! command_exists npm; then
        log_warn "npm not found; skipping caveman proxy setup."
        return
    fi

    if command_exists caveman; then
        log_success "caveman CLI already installed ($(caveman version 2>/dev/null | sed -n 's/.*"version": "\([^"]*\)".*/\1/p'))."
    elif [ "$DRY_RUN" = true ]; then
        log_dry_run "Would install the caveman CLI via: npm install -g @caveman-ai/cli"
    else
        log_info "caveman CLI not found; installing..."
        if npm install -g @caveman-ai/cli; then
            log_success "caveman CLI installed."
        else
            log_error "Failed to install @caveman-ai/cli via npm. Install it manually: npm install -g @caveman-ai/cli"
            return
        fi
    fi

    if ! command_exists caveman; then
        return
    fi

    # Capture full output before matching: piping straight into `grep -q` lets grep
    # close the pipe on first match while caveman is still writing, so it dies from
    # SIGPIPE and this script's `pipefail` reports that as a false non-match.
    local caveman_status_output
    caveman_status_output=$(caveman status 2>/dev/null || true)
    if [[ "$caveman_status_output" == *"caveman-proxy not installed"* ]]; then
        if [ "$DRY_RUN" = true ]; then
            log_dry_run "Would install the caveman proxy engine via: caveman setup --install"
        else
            log_info "caveman proxy engine not found; installing..."
            if quiet_run caveman setup --install; then
                log_success "caveman proxy engine installed."
            else
                log_error "Failed to install the caveman proxy engine. Run manually: caveman setup --install"
            fi
        fi
    else
        log_success "caveman proxy engine already installed."
    fi
}

change_shell() {
    log_step "Step 8: Changing default shell to Zsh..."
    local zsh_path
    zsh_path=$(command -v zsh 2>/dev/null || echo "/usr/bin/zsh")

    if [ "$SHELL" == "$zsh_path" ]; then
        log_info "Default shell is already $zsh_path. Skipping."
    elif [ "$DRY_RUN" = true ]; then
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

    if [ -z "$ghostty_path" ]; then
        log_warn "Ghostty is not installed. Skipping default terminal configuration."
        return 0
    fi

    local config_dir="${XDG_CONFIG_HOME:-$HOME/.config}"
    local xdg_terminals_list="$config_dir/xdg-terminals.list"
    local ghostty_entry_id="com.mitchellh.ghostty.desktop"

    if [ "$DRY_RUN" = true ]; then
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
        [ "$list" = "$xdg_terminals_list" ] || [ -e "$list" ] || continue
        local other_entries=""
        [ -f "$list" ] && other_entries=$(grep -vFx "$ghostty_entry_id" "$list" || true)
        if printf '%s\n' "$ghostty_entry_id" > "$list" \
            && { [ -z "$other_entries" ] || printf '%s\n' "$other_entries" >> "$list"; }; then
            updated=$((updated + 1))
        else
            log_error "Failed to update $list. Please add '$ghostty_entry_id' as its first line manually."
        fi
    done
    if [ "$updated" -gt 0 ]; then
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

