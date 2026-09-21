# shellcheck shell=bash
# Sourced by bin/setup.sh — sudo/profile bootstrap and all apt/package-list
# configuration: GPG keys, third-party repo sources, and the main install step.

set -euo pipefail

prompt_sudo() {
    log_info "This script requires sudo access to install packages and configure the system."
    if [[ "$DRY_RUN" = true ]]; then
        log_dry_run "Would verify sudo credentials and start refresh loop"
        return 0
    fi
    if sudo -v; then
        while kill -0 "$$" 2>/dev/null; do sudo -n true; sleep 60; done 2>/dev/null &
        # shellcheck disable=SC2034  # read in bin/lib/rollback.sh's cleanup()
        SUDO_REFRESH_PID=$!
        log_step "Sudo credentials verified. Starting setup..."
    else
        log_error "Sudo password entry failed or was cancelled."
        exit 1
    fi
}

validate_machine_preset() {
    if [[ -z "$MACHINE_PRESET" ]]; then
        log_error "Missing required --preset argument."
        echo "Use --help for usage information"
        exit 1
    fi
    if [[ -n "$PACKAGE_FILE_OVERRIDE" ]]; then
        log_success "Machine preset set to '$MACHINE_PRESET' (packages resolved externally)."
        return 0
    fi
    case "$MACHINE_PRESET" in
        work|personal|homelab)
            log_success "Machine preset set to '$MACHINE_PRESET'."
            ;;
        *)
            log_error "Invalid --preset value: '$MACHINE_PRESET'. Must be 'work', 'personal', or 'homelab' unless --package-file is also given."
            echo "Use --help for usage information"
            exit 1
            ;;
    esac
}

determine_packages_to_install() {
    if [[ -n "$PACKAGE_FILE_OVERRIDE" ]]; then
        log_info "Reading resolved package list from $PACKAGE_FILE_OVERRIDE..."
        if [[ ! -f "$PACKAGE_FILE_OVERRIDE" ]]; then
            log_error "--package-file '$PACKAGE_FILE_OVERRIDE' does not exist."
            exit 1
        fi
        mapfile -t PACKAGES_TO_INSTALL < <(grep -vE '^\s*#|^\s*$' "$PACKAGE_FILE_OVERRIDE" | sort -u)
        log_info "Found ${#PACKAGES_TO_INSTALL[@]} unique packages to install."
        return 0
    fi

    log_info "Determining which packages to install..."
    local all_packages=()

    if [ -f "$APT_PACKAGE_DIR/apt_common.txt" ]; then
        mapfile -t common_packages < <(grep -vE '^\s*#|^\s*$' "$APT_PACKAGE_DIR/apt_common.txt")
        all_packages+=( "${common_packages[@]}" )
    fi

    if [[ "$MACHINE_PRESET" == "work" || "$MACHINE_PRESET" == "personal" ]]; then
        if [ -f "$APT_PACKAGE_DIR/apt_desktop.txt" ]; then
            mapfile -t desktop_packages < <(grep -vE '^\s*#|^\s*$' "$APT_PACKAGE_DIR/apt_desktop.txt")
            all_packages+=( "${desktop_packages[@]}" )
        fi
    fi

    if [[ "$MACHINE_PRESET" == "work" ]]; then
        if [ -f "$APT_PACKAGE_DIR/apt_work.txt" ]; then
            mapfile -t work_packages < <(grep -vE '^\s*#|^\s*$' "$APT_PACKAGE_DIR/apt_work.txt")
            all_packages+=( "${work_packages[@]}" )
        fi
    fi

    if [[ "$MACHINE_PRESET" == "personal" ]]; then
        if [ -f "$APT_PACKAGE_DIR/apt_personal.txt" ]; then
            mapfile -t personal_packages < <(grep -vE '^\s*#|^\s*$' "$APT_PACKAGE_DIR/apt_personal.txt")
            all_packages+=( "${personal_packages[@]}" )
        fi
    fi

    if [[ "$MACHINE_PRESET" == "homelab" ]]; then
        if [ -f "$APT_PACKAGE_DIR/apt_homelab.txt" ]; then
            mapfile -t homelab_packages < <(grep -vE '^\s*#|^\s*$' "$APT_PACKAGE_DIR/apt_homelab.txt")
            all_packages+=( "${homelab_packages[@]}" )
        fi
    fi

    if (( ${#all_packages[@]} > 0 )); then
        while IFS= read -r -d '' package; do
            PACKAGES_TO_INSTALL+=("$package")
        done < <(printf "%s\0" "${all_packages[@]}" | sort -uz)
    fi

    log_info "Found ${#PACKAGES_TO_INSTALL[@]} unique packages to install."
}

install_core_deps() {
    log_step "Step 1: Installing core dependencies (curl, gpg, stow, zsh)..."
    if log_dry_run "Would install: curl, gpg, stow, zsh, wget, sed, build-essential"; then
        return 0
    fi
    quiet_run sudo apt-get install -y \
        curl \
        gpg \
        stow \
        zsh \
        wget \
        sed \
        build-essential
    log_success "Core dependencies installed."
}

disable_snapd() {
    log_step "Step 2: Disabling and removing snapd..."

    log_info "Stowing 'system' package to / to block snapd..."
    if log_dry_run "Would stow 'system' package to / (includes snapd block preferences)"; then
        if command_exists snap; then
            log_dry_run "Would remove snap packages and snapd"
        else
            log_dry_run "Snapd not installed, would skip removal"
        fi
        return 0
    fi
    cd "$DOTFILES_DIR"
    local stow_exit
    if quiet_run sudo stow --dir="$DOTFILES_DIR" --restow --target=/ --verbose=1 system; then
        stow_exit=0
    else
        stow_exit=$?
    fi
    cd "$HOME"

    if [[ $stow_exit -eq 0 ]]; then
        track_change "STOW_ROOT:system"
    fi

    if command_exists snap; then
        local snaps=()
        mapfile -t snaps < <(snap list --all 2>/dev/null | awk 'NR>1 {print $1}')

        if (( ${#snaps[@]} > 0 )); then
            log_info "Removing ${#snaps[@]} snap packages..."
            for snap_pkg in "${snaps[@]}"; do
                log_info "Removing snap package: $snap_pkg"
                quiet_run sudo snap remove --purge "$snap_pkg" || log_warn "Failed to remove snap package '$snap_pkg'. Continuing..."
            done
        else
            log_info "No snap packages found to remove."
        fi

        log_info "Removing snapd apt package..."
        quiet_run sudo apt-get remove -y --purge snapd || log_warn "Failed to remove snapd apt package (it may be already removed)."
        quiet_run sudo apt-get -y autoremove --purge
        log_success "Snapd and all snap packages removed."
    else
        log_info "Snapd is not installed. Skipping removal."
    fi
}

strip_snap_from_system_path() {
    log_step "Step 2b: Removing /snap/bin from the system PATH..."

    local env_file="/etc/environment"

    if ! grep -q '/snap/bin' "$env_file" 2>/dev/null; then
        log_info "No /snap/bin in $env_file. Skipping."
        return 0
    fi

    if [[ "$DRY_RUN" = true ]]; then
        log_dry_run "Would back up $env_file and remove /snap/bin from its PATH"
        return 0
    fi

    local backup_path
    backup_path="$env_file.backup-$(date +%s)"
    sudo cp -a "$env_file" "$backup_path"
    track_change "FILE_BACKUP:$backup_path"

    # Strip the colon along with the entry — a bare '' element in PATH means the cwd.
    sudo sed -i -e 's#:/snap/bin##g' -e 's#/snap/bin:##g' "$env_file"

    if grep -q '/snap/bin' "$env_file"; then
        log_warn "Could not remove /snap/bin from $env_file (is it the only PATH entry?). Left as-is."
        return 0
    fi

    log_success "/snap/bin removed from $env_file (backup: $backup_path)."
    log_warn "Log out and back in for the new system PATH to apply."
}

# Prints the host's Ubuntu codename (e.g. noble), read from os_release_file
# (default /etc/os-release, overridable for tests). Falls back to 'noble'
# with a warning if the file or VERSION_CODENAME is missing.
# shellcheck disable=SC2120
detect_ubuntu_codename() {
    local os_release_file="${1:-/etc/os-release}"
    local codename=""
    # Assigned via `if` rather than a bare `codename=$(...)`: under `set -e`, a
    # bare assignment aborts the script the instant sourcing fails or
    # VERSION_CODENAME is unset, before the fallback below ever runs.
    if [ -f "$os_release_file" ]; then
        # shellcheck disable=SC1090
        if ! codename=$(. "$os_release_file" && echo "${VERSION_CODENAME:-}"); then
            codename=""
        fi
    fi
    if [[ -z "$codename" ]]; then
        log_warn "Could not detect Ubuntu codename; defaulting to 'noble'."
        codename="noble"
    fi
    printf '%s\n' "$codename"
}

apt_prefix_selected() {
    local prefix="$1" pkg
    for pkg in "${PACKAGES_TO_INSTALL[@]}"; do
        if [[ "$pkg" == "$prefix"* ]]; then
            echo 1
            return
        fi
    done
    echo 0
}

download_apt_gpg_keys() {
    local pgadmin_selected="$1" postgresql_selected="$2" teleport_selected="$3"
    log_info "Downloading all required GPG keys..."

    if [[ "$DRY_RUN" = true ]]; then
        if array_contains "google-chrome-stable" "${PACKAGES_TO_INSTALL[@]}"; then log_dry_run "Would download Google Chrome GPG key"; fi
        if array_contains "code" "${PACKAGES_TO_INSTALL[@]}"; then log_dry_run "Would download VS Code GPG key"; fi
        if array_contains "1password" "${PACKAGES_TO_INSTALL[@]}"; then log_dry_run "Would download 1Password GPG keys"; fi
        if array_contains "docker-ce" "${PACKAGES_TO_INSTALL[@]}"; then log_dry_run "Would download Docker GPG key"; fi
        if array_contains "gh" "${PACKAGES_TO_INSTALL[@]}"; then log_dry_run "Would download GitHub CLI GPG key"; fi
        if [[ "$teleport_selected" -eq 1 ]]; then log_dry_run "Would download Teleport GPG key"; fi
        if [[ "$pgadmin_selected" -eq 1 ]]; then log_dry_run "Would download pgAdmin GPG key"; fi
        if [[ "$postgresql_selected" -eq 1 ]]; then log_dry_run "Would download PostgreSQL GPG key"; fi
    else
        if array_contains "google-chrome-stable" "${PACKAGES_TO_INSTALL[@]}"; then wget -q -O - https://dl.google.com/linux/linux_signing_key.pub | sudo gpg --dearmor --yes -o /usr/share/keyrings/google-chrome-keyring.gpg; fi
        if array_contains "code" "${PACKAGES_TO_INSTALL[@]}"; then wget -qO- https://packages.microsoft.com/keys/microsoft.asc | sudo gpg --dearmor --yes -o /usr/share/keyrings/packages.microsoft.gpg; fi
        if array_contains "1password" "${PACKAGES_TO_INSTALL[@]}"; then
            curl -sS https://downloads.1password.com/linux/keys/1password.asc | sudo gpg --dearmor --yes --output /usr/share/keyrings/1password-archive-keyring.gpg
            curl -sS https://downloads.1password.com/linux/keys/1password.asc | sudo gpg --dearmor --yes --output /usr/share/debsig/keyrings/AC2D62742012EA22/debsig.gpg
        fi
        if array_contains "docker-ce" "${PACKAGES_TO_INSTALL[@]}"; then curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor --yes -o /usr/share/keyrings/docker.gpg; fi
        if array_contains "gh" "${PACKAGES_TO_INSTALL[@]}"; then curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg | sudo gpg --dearmor --yes -o /usr/share/keyrings/githubcli-archive-keyring.gpg; fi
        if [ "$teleport_selected" -eq 1 ]; then curl -fsSL https://apt.releases.teleport.dev/gpg | sudo gpg --dearmor --yes -o /usr/share/keyrings/teleport-archive-keyring.gpg; fi
        if [ "$pgadmin_selected" -eq 1 ]; then curl -fsSL https://www.pgadmin.org/static/packages_pgadmin_org.pub | sudo gpg --dearmor --yes -o /usr/share/keyrings/pgadmin4-archive-keyring.gpg; fi
        if [ "$postgresql_selected" -eq 1 ]; then curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc | sudo gpg --dearmor --yes -o /usr/share/keyrings/postgresql-archive-keyring.gpg; fi
    fi
}

configure_apt_ppas() {
    log_info "Adding and configuring APT repositories..."
    if [[ "$DRY_RUN" = true ]]; then
        if array_contains "firefox" "${PACKAGES_TO_INSTALL[@]}"; then
            log_dry_run "Would add Mozilla PPA and configure Firefox pinning"
        fi
        if array_contains "ghostty" "${PACKAGES_TO_INSTALL[@]}"; then
            log_dry_run "Would add ghostty PPA (ppa:mkasberg/ghostty-ubuntu)"
        fi
        if array_contains "1password" "${PACKAGES_TO_INSTALL[@]}"; then
            log_dry_run "Would configure 1Password debsig policy"
        fi
    else
        if array_contains "firefox" "${PACKAGES_TO_INSTALL[@]}"; then
            quiet_run sudo add-apt-repository -y ppa:mozillateam/ppa
            echo '
Package: firefox*
Pin: release o=LP-PPA-mozillateam
Pin-Priority: 1001
' | sudo tee /etc/apt/preferences.d/mozillateam-firefox-pin > /dev/null
        fi
        if array_contains "ghostty" "${PACKAGES_TO_INSTALL[@]}"; then
            quiet_run sudo add-apt-repository -y ppa:mkasberg/ghostty-ubuntu
        fi
        if array_contains "1password" "${PACKAGES_TO_INSTALL[@]}"; then curl -sS https://downloads.1password.com/linux/debian/debsig/1password.pol | sudo tee /etc/debsig/policies/AC2D62742012EA22/1password.pol > /dev/null; fi
    fi
}

stow_apt_source_files() {
    local pgadmin_selected="$1" postgresql_selected="$2" teleport_selected="$3"

    local stow_apt_dir="$DOTFILES_DIR/apt"
    local temp_stow_backup_dir
    temp_stow_backup_dir=$(mktemp -d)
    register_temp_dir "$temp_stow_backup_dir"

    local source_map=(
        "1password:1password.sources"
        "google-chrome-stable:google-chrome.sources"
        "code:vscode.sources"
        "gh:github-cli.sources"
        "pgadmin4:pgadmin4.sources"
        "postgresql:postgresql.sources"
    )

    for mapping in "${source_map[@]}"; do
        local pkg_key="${mapping%%:*}"
        local source_file="${mapping#*:}"
        local source_file_path="$stow_apt_dir/etc/apt/sources.list.d/$source_file"
        local needed=0

        if [[ "$pkg_key" == "pgadmin4" ]]; then
            if [[ "$pgadmin_selected" -eq 1 ]]; then needed=1; fi
        elif [[ "$pkg_key" == "postgresql" ]]; then
            if [[ "$postgresql_selected" -eq 1 ]]; then needed=1; fi
        elif [[ "$pkg_key" == "teleport" ]]; then
            if [[ "$teleport_selected" -eq 1 ]]; then needed=1; fi
        elif array_contains "$pkg_key" "${PACKAGES_TO_INSTALL[@]}"; then
            needed=1
        fi

        if [[ -f "$source_file_path" ]] && [[ $needed -eq 0 ]]; then
            log_info "Temporarily hiding unneeded source file: $source_file"
            mkdir -p "$(dirname "$temp_stow_backup_dir/$source_file")"
            mv "$source_file_path" "$temp_stow_backup_dir/$source_file"
        fi
    done

    log_info "Stowing required 'apt' source files to / ..."

    cd "$DOTFILES_DIR"
    local stow_status stow_output
    # Assigned via `if` rather than a bare `stow_output=$(...)`: under `set -e`, a bare
    # assignment aborts the script the instant stow (inside the pipe) fails, before
    # stow_status=$? ever runs — skipping the conflict backup/retry logic below entirely.
    if stow_output=$(sudo stow --dir="$DOTFILES_DIR" --restow --no-folding --target=/ --verbose=1 apt 2>&1 | grep -v "WARNING\|existing target"); then
        stow_status=0
    else
        stow_status=$?
    fi
    if [[ "$VERBOSITY" -ge 2 ]] || [[ $stow_status -ne 0 ]]; then
        printf '%s\n' "$stow_output"
    fi
    cd "$HOME"

    if [[ $stow_status -ne 0 ]]; then
        log_warn "Stow encountered conflicts. Attempting to resolve..."

        local conflict_files
        # shellcheck disable=SC2015
        conflict_files=$( (cd "$DOTFILES_DIR" && sudo stow --dir="$DOTFILES_DIR" --no --no-folding --target=/ --verbose=1 apt 2>&1 | perl -ne 'if (/existing target.*?:\s*(\S+)/) { print "$1\n" } elsif (/existing target\s+(\S+)\s+since/) { print "$1\n" }') || true)

        if [[ -n "$conflict_files" ]]; then
            local stow_backup_root="/var/backups/dotfiles-stow"
            sudo mkdir -p "$stow_backup_root"
            while IFS= read -r conflict_file; do
                if [[ -f "/$conflict_file" ]]; then
                    log_info "Backing up conflicting file: $conflict_file"
                    local backup_path
                    backup_path="$stow_backup_root/$(basename "$conflict_file").backup-$(date +%s)"
                    sudo mv "/$conflict_file" "$backup_path"
                    track_change "FILE_BACKUP:$backup_path"
                fi
            done <<< "$conflict_files"

            cd "$DOTFILES_DIR"
            quiet_run sudo stow --dir="$DOTFILES_DIR" --restow --no-folding --target=/ --verbose=1 apt
            cd "$HOME"
            track_change "STOW_ROOT:apt"
        fi
    else
        track_change "STOW_ROOT:apt"
    fi

    log_info "Restoring hidden source files..."
    if [[ -d "$temp_stow_backup_dir" ]] && [[ "$(ls -A "$temp_stow_backup_dir")" ]]; then
        rsync -a "$temp_stow_backup_dir/" "$stow_apt_dir/etc/apt/sources.list.d/"
    fi
    rm -rf -- "$temp_stow_backup_dir"
}

generate_templated_apt_sources() {
    local teleport_selected="$1"

    if array_contains "docker-ce" "${PACKAGES_TO_INSTALL[@]}" || [ "$teleport_selected" -eq 1 ]; then
        local host_codename
        # shellcheck disable=SC2119
        host_codename=$(detect_ubuntu_codename)

        if array_contains "docker-ce" "${PACKAGES_TO_INSTALL[@]}"; then
            log_info "Configuring Docker apt repository for suite: $host_codename"
            sed "s/^Suites:.*/Suites: $host_codename/" "$DOTFILES_DIR/apt-templates/docker.sources.template" | sudo tee /etc/apt/sources.list.d/docker.sources > /dev/null
            track_change "FILE_CREATED:/etc/apt/sources.list.d/docker.sources"
        fi

        if [[ "$teleport_selected" -eq 1 ]]; then
            log_info "Configuring Teleport apt repository for suite: $host_codename"
            sed "s/^Suites:.*/Suites: $host_codename/" "$DOTFILES_DIR/apt-templates/teleport.sources.template" | sudo tee /etc/apt/sources.list.d/teleport.sources > /dev/null
            track_change "FILE_CREATED:/etc/apt/sources.list.d/teleport.sources"
        fi
    fi
}

configure_apt_sources() {
    log_step "Step 3: Configuring third-party apt sources..."

    if [[ "$DRY_RUN" = true ]]; then
        log_dry_run "Would create directories for GPG keys and debsig policies"
    else
        sudo mkdir -p /usr/share/keyrings /etc/debsig/policies/AC2D62742012EA22 /usr/share/debsig/keyrings/AC2D62742012EA22
    fi

    local pgadmin_selected postgresql_selected teleport_selected
    pgadmin_selected=$(apt_prefix_selected "pgadmin4")
    postgresql_selected=$(apt_prefix_selected "postgresql")
    teleport_selected=$(apt_prefix_selected "teleport")

    download_apt_gpg_keys "$pgadmin_selected" "$postgresql_selected" "$teleport_selected"
    configure_apt_ppas

    # Dry-run must return before the code below, which physically moves
    # tracked .sources files into a temp dir — checking DRY_RUN after that
    # would make --dry-run mutate the working tree.
    if [[ "$DRY_RUN" = true ]]; then
        log_dry_run "Would stow 'apt' package to / (includes third-party repo sources)"
        log_dry_run "Would handle any stow conflicts by backing up existing files"
        if array_contains "docker-ce" "${PACKAGES_TO_INSTALL[@]}"; then
            log_dry_run "Would generate /etc/apt/sources.list.d/docker.sources for the detected Ubuntu codename"
        fi
        if [[ "$teleport_selected" -eq 1 ]]; then
            log_dry_run "Would generate /etc/apt/sources.list.d/teleport.sources for the detected Ubuntu codename"
        fi
        log_success "Apt sources configured (dry-run)."
        return 0
    fi

    stow_apt_source_files "$pgadmin_selected" "$postgresql_selected" "$teleport_selected"
    generate_templated_apt_sources "$teleport_selected"

    log_success "Apt sources configured."
}


install_packages() {
    log_step "Step 4: Installing packages..."

    local custom_install_packages=("oh-my-zsh" "sdkman" "nvm" "lazydocker" "zoom" "istioctl" "awscli" "slack-desktop" "jetbrains-toolbox" "antigravity-ide" "zizmor" "ruff" "coderabbit")

    if array_contains "oh-my-zsh" "${PACKAGES_TO_INSTALL[@]}"; then
        install_omz
    fi
    if array_contains "sdkman" "${PACKAGES_TO_INSTALL[@]}"; then
        install_sdkman
    fi
    if array_contains "nvm" "${PACKAGES_TO_INSTALL[@]}"; then
        install_nvm
    fi
    if array_contains "lazydocker" "${PACKAGES_TO_INSTALL[@]}"; then
        install_lazydocker
    fi
    if array_contains "zoom" "${PACKAGES_TO_INSTALL[@]}"; then
        install_zoom
    fi
    if array_contains "istioctl" "${PACKAGES_TO_INSTALL[@]}"; then
        install_istioctl
    fi
    if array_contains "awscli" "${PACKAGES_TO_INSTALL[@]}"; then
        install_awscli
    fi
    if array_contains "zizmor" "${PACKAGES_TO_INSTALL[@]}"; then
        install_zizmor
    fi
    if array_contains "ruff" "${PACKAGES_TO_INSTALL[@]}"; then
        install_ruff
    fi
    if array_contains "coderabbit" "${PACKAGES_TO_INSTALL[@]}"; then
        install_coderabbit
    fi
    if array_contains "slack-desktop" "${PACKAGES_TO_INSTALL[@]}"; then
        install_slack
    fi
    if array_contains "jetbrains-toolbox" "${PACKAGES_TO_INSTALL[@]}"; then
        install_jetbrains_toolbox
    fi
    if array_contains "antigravity-ide" "${PACKAGES_TO_INSTALL[@]}"; then
        install_antigravity_ide
    fi

    local apt_packages_to_install=()
    for pkg in "${PACKAGES_TO_INSTALL[@]}"; do
        if ! array_contains "$pkg" "${custom_install_packages[@]}"; then
            apt_packages_to_install+=("$pkg")
        fi
    done

    if (( ${#apt_packages_to_install[@]} > 0 )); then
        if [[ "$DRY_RUN" = true ]]; then
            log_dry_run "Would update package lists"
            log_dry_run "Would install ${#apt_packages_to_install[@]} apt packages: ${apt_packages_to_install[*]}"
        else
            log_info "Updating package lists..."
            quiet_run sudo apt-get update
            log_info "Installing ${#apt_packages_to_install[@]} apt packages..."
            quiet_run sudo DEBIAN_FRONTEND=noninteractive apt-get install -y "${apt_packages_to_install[@]}"
            log_success "All apt packages installed."
            # Remove legacy .list files that some packages auto-create when a .sources counterpart is managed by stow
            local sources_dir="/etc/apt/sources.list.d"
            for sources_file in "$sources_dir"/*.sources; do
                local base
                base=$(basename "$sources_file" .sources)
                if [[ -f "$sources_dir/$base.list" ]]; then
                    log_info "Removing duplicate apt source: $base.list (superseded by $base.sources)"
                    sudo rm -f "$sources_dir/$base.list"
                fi
            done
        fi
    else
        log_warn "No apt packages to install."
    fi
}

enable_gpaste_extension() {
    if ! array_contains "gnome-shell-extension-gpaste" "${PACKAGES_TO_INSTALL[@]}"; then
        return 0
    fi

    log_step "Step 4b: Enabling GPaste GNOME Shell extension..."

    if ! command_exists gnome-extensions; then
        log_warn "gnome-extensions command not found. Skipping GPaste extension enable."
        return 0
    fi

    if [[ "$DRY_RUN" = true ]]; then
        log_dry_run "Would enable GPaste@gnome-shell-extensions.gnome.org"
        return 0
    fi

    if gnome-extensions enable GPaste@gnome-shell-extensions.gnome.org 2>/dev/null; then
        log_success "GPaste extension enabled."
    else
        log_warn "Failed to enable GPaste extension (no active GNOME Shell session?)."
        log_warn "Enable it manually with: gnome-extensions enable GPaste@gnome-shell-extensions.gnome.org"
    fi
}

install_github_bins() {
    log_step "Step 5: Installing .deb packages from GitHub..."

    local github_bins_file="$APT_PACKAGE_DIR/github_bins.txt"

    if [[ ! -f "$github_bins_file" ]] || [[ ! -s "$github_bins_file" ]]; then
        log_warn "github_bins.txt not found or is empty. Skipping."
        return
    fi

    if [[ "$DRY_RUN" = true ]]; then
        while IFS= read -r line || [[ -n "$line" ]]; do
            if [[ "$line" =~ ^\s*# ]] || [[ -z "$line" ]]; then
                continue
            fi
            local repo version filename
            read -r repo version filename <<< "$line"
            if [[ -n "$repo" && -n "$version" && -n "$filename" ]]; then
                log_dry_run "Would download and install $filename from $repo v$version"
            fi
        done < "$github_bins_file"
        return 0
    fi

    local temp_dir
    temp_dir=$(mktemp -d)
    register_temp_dir "$temp_dir"

    # Self-clearing: a RETURN trap set here also re-fires once in the
    # immediate caller's frame, where $temp_dir is unbound under `set -u`.
    # Clear it after first use.
    trap 'rm -rf -- "$temp_dir"; trap - RETURN' RETURN

    while IFS= read -r line || [[ -n "$line" ]]; do
        if [[ "$line" =~ ^\s*# ]] || [[ -z "$line" ]]; then
            continue
        fi

        local repo version filename
        read -r repo version filename <<< "$line"

        if [[ -z "$repo" || -z "$version" || -z "$filename" ]]; then
            log_error "Invalid line in github_bins.txt: '$line'"
            continue
        fi

        local pkg_name=${filename%%_*}
        if dpkg -l | grep -q "^ii.*$pkg_name"; then
            log_info "Package $pkg_name is already installed. Skipping."
            continue
        fi

        local url="https://github.com/$repo/releases/download/v$version/$filename"
        local deb_path="$temp_dir/$filename"

        log_info "Fetching $filename v$version from $repo..."
        if download_with_cache "github-bins/$repo" "$version-$filename" "$url" "$deb_path"; then
            [[ "$DOWNLOAD_CACHE_HIT" = true ]] && log_info "(using cached .deb)"
            log_info "Installing $filename..."
            if quiet_run sudo dpkg -i "$deb_path"; then
                log_success "Successfully installed $filename."
            else
                log_error "Failed to install $filename. Running 'apt --fix-broken install'..."
                quiet_run sudo apt-get -y --fix-broken install
            fi
        else
            log_error "Failed to download $filename from $url"
        fi
    done < "$github_bins_file"
}

configure_docker_group() {
    if array_contains "docker-ce" "${PACKAGES_TO_INSTALL[@]}"; then
        log_step "Step 6: Configuring docker group..."

        if [[ "$DRY_RUN" = true ]]; then
            if ! getent group docker >/dev/null; then
                log_dry_run "Would create docker group"
            fi
            if ! groups "$USER" | grep &>/dev/null "\bdocker\b"; then
                log_dry_run "Would add user $USER to docker group"
            else
                log_info "User $USER is already in docker group."
            fi
            return 0
        fi

        if ! getent group docker >/dev/null; then
            log_info "Creating docker group..."
            sudo groupadd docker
        fi

        if ! groups "$USER" | grep &>/dev/null "\bdocker\b"; then
            log_info "Adding user $USER to docker group..."
            sudo usermod -aG docker "$USER"
            track_change "DOCKER_GROUP:$USER"
            log_success "User added to docker group."
        else
            log_info "User $USER is already in docker group."
        fi
    fi
}

