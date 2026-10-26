# shellcheck shell=bash
# Sourced by bin/setup.sh — third-party tool installers not available via apt
# (the github-release binary installers; sdkman, oh-my-zsh and nvm live in
# bin/dotfiles_setup/tools.py).

set -euo pipefail

lazydocker_is_installed() { command -v lazydocker &> /dev/null; }

resolve_lazydocker() {
    local version
    version=$(curl -s "https://api.github.com/repos/jesseduffield/lazydocker/releases/latest" | grep -Po '"tag_name": "v\K[^"]*' || true)
    if [[ -z "$version" ]]; then
        return 1
    fi
    print_resolved "$version" \
        "https://github.com/jesseduffield/lazydocker/releases/latest/download/lazydocker_${version}_Linux_x86_64.tar.gz" \
        "$version.tar.gz"
}

install_lazydocker_step() {
    local temp_dir="$1"
    sudo install "$temp_dir/lazydocker" /usr/local/bin
}

install_lazydocker() {
    install_from_url "lazydocker" lazydocker_is_installed resolve_lazydocker targz install_lazydocker_step
}

zoom_is_installed() { grep -q "^ii  zoom " < <(dpkg -l); }

resolve_zoom() {
    local url="https://zoom.us/client/latest/zoom_amd64.deb"
    local version
    version=$(curl -sI --max-time 15 "$url" | grep -i '^location:' | tail -1 | grep -oP '/prod/\K[0-9.]+' || true)
    if [[ -z "$version" ]]; then
        version="latest"
    fi
    print_resolved "$version" "$url" "zoom_amd64-$version.deb"
}

install_zoom_step() {
    local artifact_path="$3"
    install_deb_or_fix_broken "$artifact_path" "zoom"
}

install_zoom() {
    install_from_url "Zoom" zoom_is_installed resolve_zoom deb install_zoom_step
}

slack_is_installed() { grep -q "^ii  slack-desktop " < <(dpkg -l); }

resolve_slack() {
    local version
    version=$(curl_https -sL "https://slack.com/downloads/linux" | grep -oP 'Version \K[0-9]+\.[0-9]+\.[0-9]+' | head -1 || true)
    if [[ -z "$version" ]]; then
        return 1
    fi
    print_resolved "$version" \
        "https://downloads.slack-edge.com/desktop-releases/linux/x64/${version}/slack-desktop-${version}-amd64.deb" \
        "slack-desktop-$version-amd64.deb"
}

install_slack_step() {
    local artifact_path="$3"
    install_deb_or_fix_broken "$artifact_path" "slack-desktop"
    local install_status=$?
    # Slack's postinst drops an apt repo file with no Signed-By key reference,
    # which trips apt's "Missing Signed-By" warning. We update via direct .deb
    # download above, not this repo, so just remove it.
    sudo rm -f /etc/apt/sources.list.d/slack.sources /etc/apt/sources.list.d/slack.list
    return "$install_status"
}

install_slack() {
    install_from_url "Slack" slack_is_installed resolve_slack deb install_slack_step
}

jetbrains_toolbox_is_installed() { [[ -f "$HOME/.local/share/JetBrains/Toolbox/bin/jetbrains-toolbox" ]]; }

resolve_jetbrains_toolbox() {
    local url
    url=$(curl -s 'https://data.services.jetbrains.com/products/releases?code=TBA&latest=true&type=release' \
        | grep -oP '"linux":\{"link":"\K[^"]+' || true)
    if [[ -z "$url" ]]; then
        return 1
    fi
    print_resolved "" "$url" "$(basename "$url")"
}

install_jetbrains_toolbox_step() {
    local temp_dir="$1"
    local extracted_dir
    extracted_dir=$(find "$temp_dir" -name "jetbrains-toolbox" -type f | head -1 | xargs dirname)
    if [[ -z "$extracted_dir" ]]; then
        log_error "Could not find jetbrains-toolbox binary in archive."
        return 1
    fi
    local install_dir="$HOME/.local/share/JetBrains/Toolbox/bin"
    if ! mkdir -p "$install_dir"; then
        return 1
    fi
    if ! cp -r "$extracted_dir"/. "$install_dir/"; then
        return 1
    fi
    chmod +x "$install_dir/jetbrains-toolbox"
}

install_jetbrains_toolbox() {
    install_from_url "JetBrains Toolbox" jetbrains_toolbox_is_installed resolve_jetbrains_toolbox targz install_jetbrains_toolbox_step
}

resolve_antigravity_ide_build() {
    local arch_dir="$1"
    local pinned_url="https://edgedl.me.gvt1.com/edgedl/release2/j0qc3/antigravity/stable/2.1.1-6123990880747520/$arch_dir/Antigravity%20IDE.tar.gz"

    log_info "Resolving the latest Antigravity IDE build..." >&2
    local download_url
    download_url=$(curl -sS --compressed "https://antigravity.google/download" \
        | grep -oP "https://edgedl\.me\.gvt1\.com/edgedl/release2/[^\"'\\\\ /]+/antigravity/stable/[0-9][^\"'\\\\ ]*/$arch_dir/Antigravity%20IDE\.tar\.gz" \
        | head -1) || true

    if [[ -z "$download_url" ]]; then
        log_warn "Could not resolve the latest build. Falling back to the pinned URL." >&2
        download_url="$pinned_url"
    fi

    local build
    build=$(printf '%s' "$download_url" | grep -oP 'antigravity/stable/\K[^/]+') || true
    local version="${build%%-*}"

    print_resolved "$download_url" "$build" "$version"
}

# Downloads (or reuses a build-keyed cache of) the Antigravity IDE tarball into
# $temp_dir, then extracts it. Echoes the extracted app directory on success.
fetch_and_extract_antigravity_ide() {
    local download_url="$1" build="$2" version="$3" temp_dir="$4"
    local tarball_path="$temp_dir/antigravity-ide.tar.gz"

    # Cache the tarball by build ID so a crash or retry after this point (e.g. the
    # install steps below, which run after the download) doesn't re-fetch ~220MB.
    local cache_dir="${XDG_CACHE_HOME:-$HOME/.cache}/dotfiles-setup/antigravity-ide"
    local cached_tarball="$cache_dir/$build.tar.gz"
    mkdir -p "$cache_dir"

    if [[ -s "$cached_tarball" ]]; then
        log_info "Using cached Antigravity IDE ${version:-unknown} tarball." >&2
        cp -- "$cached_tarball" "$tarball_path"
    else
        log_info "Downloading Antigravity IDE ${version:-unknown} from $download_url..." >&2
        if ! curl_https -fsSL -o "$tarball_path" "$download_url"; then
            log_error "Failed to download Antigravity IDE from $download_url"
            log_warn "$MSG_CONTINUING_SETUP" >&2
            return 1
        fi
        # Write-then-rename so an interrupted run never leaves a corrupt cache entry.
        cp -- "$tarball_path" "$cache_dir/.$build.tar.gz.tmp" && mv -f -- "$cache_dir/.$build.tar.gz.tmp" "$cached_tarball"
        find "$cache_dir" -maxdepth 1 -type f -name '*.tar.gz' ! -name "$(basename "$cached_tarball")" -delete 2>/dev/null || true
    fi

    log_info "Extracting Antigravity IDE..." >&2
    if ! tar -xzf "$tarball_path" -C "$temp_dir"; then
        log_error "Failed to extract Antigravity IDE."
        log_warn "$MSG_CONTINUING_SETUP" >&2
        return 1
    fi

    local extracted_bin
    extracted_bin=$(find "$temp_dir" -maxdepth 2 -type f -name antigravity-ide | head -1)
    local extracted_dir=""
    [[ -n "$extracted_bin" ]] && extracted_dir=$(dirname -- "$extracted_bin")

    if [[ -z "$extracted_dir" ]]; then
        log_error "Could not find the antigravity-ide binary in the archive."
        log_warn "$MSG_CONTINUING_SETUP" >&2
        return 1
    fi

    printf '%s\n' "$extracted_dir"
}

# Copies the extracted app into place, wires up its launcher/sandbox/desktop
# entry, and records the installed build ID.
place_antigravity_ide() {
    local extracted_dir="$1" install_dir="$2" icon_path="$3" desktop_path="$4" build_file="$5" build="$6" version="$7"
    # Staged in a sibling directory and swapped into place only once fully
    # built, so a failure below leaves any existing installation untouched
    # instead of removing it before the replacement is ready.
    local staging_dir="$install_dir.staging"

    log_info "Installing Antigravity IDE to $install_dir..."
    sudo rm -rf -- "$staging_dir"
    if ! sudo mkdir -p "$staging_dir"; then
        log_error "Failed to create $staging_dir."
        log_warn "$MSG_CONTINUING_SETUP"
        return 1
    fi
    if ! sudo cp -r "$extracted_dir"/. "$staging_dir/"; then
        log_error "Failed to copy Antigravity IDE into $staging_dir."
        log_warn "$MSG_CONTINUING_SETUP"
        sudo rm -rf -- "$staging_dir"
        return 1
    fi
    if ! sudo chown -R root:root "$staging_dir"; then
        log_error "Failed to set ownership on $staging_dir."
        log_warn "$MSG_CONTINUING_SETUP"
        sudo rm -rf -- "$staging_dir"
        return 1
    fi
    # Electron's SUID sandbox helper; without root ownership Ubuntu's userns restriction blocks startup.
    if [[ -f "$staging_dir/chrome-sandbox" ]]; then
        if ! sudo chmod 4755 "$staging_dir/chrome-sandbox"; then
            log_error "Failed to set the SUID bit on chrome-sandbox."
            log_warn "$MSG_CONTINUING_SETUP"
            sudo rm -rf -- "$staging_dir"
            return 1
        fi
    else
        log_warn "chrome-sandbox not found in the Antigravity IDE archive; the sandbox may not start."
    fi

    sudo mv -- "$install_dir" "$install_dir.old" 2>/dev/null || true
    if ! sudo mv -- "$staging_dir" "$install_dir"; then
        log_error "Failed to move staged Antigravity IDE into $install_dir."
        log_warn "$MSG_CONTINUING_SETUP"
        sudo rm -rf -- "$staging_dir"
        [[ -d "$install_dir.old" ]] && sudo mv -- "$install_dir.old" "$install_dir"
        return 1
    fi
    sudo rm -rf -- "$install_dir.old"

    if ! sudo ln -sfn "$install_dir/antigravity-ide" /usr/local/bin/antigravity-ide; then
        log_error "Failed to symlink /usr/local/bin/antigravity-ide."
        log_warn "$MSG_CONTINUING_SETUP"
        return 1
    fi

    install_antigravity_ide_icon "$install_dir/resources/app/resources/linux/code.png" "$icon_path"

    if ! sudo tee "$desktop_path" > /dev/null <<EOF
[Desktop Entry]
Type=Application
Name=Antigravity IDE
Comment=Google Antigravity agent-first development platform
Exec=$install_dir/antigravity-ide %U
Icon=antigravity-ide
Terminal=false
Categories=Development;IDE;
StartupWMClass=Antigravity IDE
MimeType=x-scheme-handler/antigravity-ide;
EOF
    then
        log_error "Failed to write $desktop_path."
        log_warn "$MSG_CONTINUING_SETUP"
        return 1
    fi
    sudo update-desktop-database /usr/share/applications 2>/dev/null || true

    if ! printf '%s\n' "$build" | sudo tee "$build_file" > /dev/null; then
        log_error "Failed to record the installed build in $build_file."
        log_warn "$MSG_CONTINUING_SETUP"
        return 1
    fi
    log_success "Antigravity IDE ${version:-unknown} installed to $install_dir."
}

# Removes the legacy "Antigravity" (pre-rename) install this replaces, if present.
remove_legacy_antigravity() {
    if [[ -d /opt/antigravity ]]; then
        sudo rm -rf -- /opt/antigravity
        sudo rm -f -- /usr/local/bin/antigravity /usr/share/applications/antigravity.desktop /usr/share/icons/hicolor/512x512/apps/antigravity.png
        sudo update-desktop-database /usr/share/applications 2>/dev/null || true
        log_info "Removed the legacy Antigravity install."
    fi
}

install_antigravity_ide() {
    log_info "Installing Antigravity IDE..."

    local arch_dir
    case "$(uname -m)" in
        x86_64) arch_dir="linux-x64" ;;
        aarch64 | arm64) arch_dir="linux-arm" ;;
        *)
            log_error "No Antigravity IDE build for architecture $(uname -m)."
            log_warn "$MSG_CONTINUING_SETUP"
            return 0
            ;;
    esac

    local install_dir="/opt/antigravity-ide"
    local build_file="$install_dir/.installed-build"
    local icon_path="/usr/share/icons/hicolor/512x512/apps/antigravity-ide.png"
    local desktop_path="/usr/share/applications/antigravity-ide.desktop"

    if [[ "$DRY_RUN" = true ]]; then
        log_dry_run "Would resolve the latest Antigravity IDE build from https://antigravity.google/download"
        log_dry_run "Would install Antigravity IDE to $install_dir with a launcher and desktop entry"
        return 0
    fi

    local download_url build version
    IFS=$'\t' read -r download_url build version <<< "$(resolve_antigravity_ide_build "$arch_dir")"

    if [[ -f "$build_file" ]] && [[ "$(cat "$build_file")" = "$build" ]]; then
        log_info "Antigravity IDE $version is already installed. Skipping."
        return 0
    fi

    local temp_dir
    temp_dir=$(mktemp -d)
    register_temp_dir "$temp_dir"
    # Self-clearing: a RETURN trap set here also re-fires once in the
    # immediate caller's frame (install_packages()), where $temp_dir is
    # unbound under `set -u` — same gotcha as install_from_url in helpers.sh.
    trap 'rm -rf -- "$temp_dir"; trap - RETURN' RETURN

    local extracted_dir
    extracted_dir=$(fetch_and_extract_antigravity_ide "$download_url" "$build" "$version" "$temp_dir") || return 0

    place_antigravity_ide "$extracted_dir" "$install_dir" "$icon_path" "$desktop_path" "$build_file" "$build" "$version" || return 0

    remove_legacy_antigravity
}

# Antigravity IDE ships resources/app unpacked (no app.asar), so the icon is a plain file.
install_antigravity_ide_icon() {
    local src="$1"
    local dest="$2"

    if [[ ! -f "$src" ]]; then
        log_warn "Antigravity IDE icon not found at $src; the launcher will use a generic icon."
        return 0
    fi

    if ! sudo mkdir -p "$(dirname "$dest")"; then
        log_warn "Could not create $(dirname "$dest"); the launcher will use a generic icon."
        return 0
    fi
    if ! sudo cp -- "$src" "$dest"; then
        log_warn "Could not write $dest; the launcher will use a generic icon."
        return 0
    fi
    sudo gtk-update-icon-cache -f -t /usr/share/icons/hicolor 2>/dev/null || true
}

istioctl_is_installed() { command -v istioctl &> /dev/null; }

resolve_istioctl() {
    local version
    version=$(curl -s "https://api.github.com/repos/istio/istio/releases/latest" | grep -Po '"tag_name": "\K[^"]*' || true)
    if [[ -z "$version" ]]; then
        return 1
    fi
    print_resolved "$version" \
        "https://github.com/istio/istio/releases/download/${version}/istio-${version}-linux-amd64.tar.gz" \
        "istio-$version-linux-amd64.tar.gz"
}

install_istioctl_step() {
    local temp_dir="$1" version="$2"
    sudo install "$temp_dir/istio-${version}/bin/istioctl" /usr/local/bin
}

install_istioctl() {
    install_from_url "istioctl" istioctl_is_installed resolve_istioctl targz install_istioctl_step
}

awscli_is_installed() { command -v aws &> /dev/null; }

# AWS exposes no version endpoint, so the cache key is fixed. Safe: this
# only runs while `aws` is absent from PATH, so a stale cache can only
# affect retries of a not-yet-successful install, never mask an upgrade.
resolve_awscli() {
    print_resolved "" "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" "awscliv2.zip"
}

install_awscli_step() {
    local temp_dir="$1"
    sudo "$temp_dir/aws/install"
}

install_awscli() {
    install_from_url "AWS CLI" awscli_is_installed resolve_awscli zip install_awscli_step
}

zizmor_is_installed() { command -v zizmor &> /dev/null; }

resolve_zizmor() {
    local version
    version=$(curl -s "https://api.github.com/repos/zizmorcore/zizmor/releases/latest" | grep -Po '"tag_name": "\K[^"]*' || true)
    if [[ -z "$version" ]]; then
        return 1
    fi
    print_resolved "$version" \
        "https://github.com/zizmorcore/zizmor/releases/download/${version}/zizmor-x86_64-unknown-linux-gnu.tar.gz" \
        "zizmor-$version.tar.gz"
}

install_zizmor_step() {
    local temp_dir="$1"
    sudo install "$temp_dir/zizmor" /usr/local/bin
}

install_zizmor() {
    install_from_url "zizmor" zizmor_is_installed resolve_zizmor targz install_zizmor_step
}

mcp_grafana_is_installed() { command -v mcp-grafana &> /dev/null; }

resolve_mcp_grafana() {
    local version
    version=$(curl -s "https://api.github.com/repos/grafana/mcp-grafana/releases/latest" | grep -Po '"tag_name": "\K[^"]*' || true)
    if [[ -z "$version" ]]; then
        return 1
    fi
    print_resolved "$version" \
        "https://github.com/grafana/mcp-grafana/releases/download/${version}/mcp-grafana_Linux_x86_64.tar.gz" \
        "mcp-grafana-$version.tar.gz"
}

install_mcp_grafana_step() {
    local temp_dir="$1"
    sudo install "$temp_dir/mcp-grafana" /usr/local/bin
}

install_mcp_grafana() {
    install_from_url "mcp-grafana" mcp_grafana_is_installed resolve_mcp_grafana targz install_mcp_grafana_step
}

coderabbit_is_installed() { command -v coderabbit &> /dev/null; }

# No apt candidate and no plain-binary GitHub release asset (installer script
# also drops the `cr` symlink coderabbitFullAudit depends on), so this goes
# through the vendor's own install script like configure_rtk_cli.
install_coderabbit() {
    log_info "Installing CodeRabbit CLI..."

    if coderabbit_is_installed; then
        log_info "CodeRabbit CLI is already installed. Skipping."
        return 0
    fi

    if [[ "$DRY_RUN" = true ]]; then
        log_dry_run "Would install the CodeRabbit CLI via https://cli.coderabbit.ai's install script."
        return 0
    fi

    if run_vendor_script "https://cli.coderabbit.ai/install.sh" sh; then
        log_success "CodeRabbit CLI installed ($(coderabbit_is_installed && coderabbit --version 2>/dev/null))."
    else
        log_error "Failed to install CodeRabbit CLI. Install it manually: curl -fsSL -o install.sh https://cli.coderabbit.ai/install.sh && sh install.sh"
    fi
}

# Downloads in full before executing so a truncated transfer never runs. Extra args go to the script.
run_vendor_script() {
    local url="$1" shell="$2" script status=0
    shift 2
    script=$(mktemp)
    curl_https -fsSL -o "$script" "$url" && "$shell" "$script" "$@" || status=$?
    rm -f "$script"
    return "$status"
}

sonarqube_cli_is_installed() { command -v sonar &> /dev/null || [[ -x "$HOME/.local/share/sonarqube-cli/bin/sonar" ]]; }

# No apt candidate. The vendor script's bin dir is already on PATH via zsh/.zshrc.
install_sonarqube_cli() {
    log_info "Installing SonarQube CLI..."

    if sonarqube_cli_is_installed; then
        log_info "SonarQube CLI is already installed. Skipping."
        return 0
    fi

    if [[ "$DRY_RUN" = true ]]; then
        log_dry_run "Would install the SonarQube CLI via SonarSource's install script."
        return 0
    fi

    local url="https://raw.githubusercontent.com/SonarSource/sonarqube-cli/refs/heads/master/user-scripts/install.sh"
    if run_vendor_script "$url" bash; then
        log_success "SonarQube CLI installed."
    else
        log_error "Failed to install SonarQube CLI. Install it manually: curl -fsSL -o install.sh $url && bash install.sh"
    fi
}

uv_is_installed() { command -v uv &> /dev/null || [[ -x "$HOME/.local/bin/uv" ]]; }

# Claude plugin MCP servers (cozempic) launch via uv/uvx.
install_uv() {
    log_info "Installing uv..."

    if uv_is_installed; then
        log_info "uv is already installed. Skipping."
        return 0
    fi

    if [[ "$DRY_RUN" = true ]]; then
        log_dry_run "Would install uv via https://astral.sh/uv/install.sh."
        return 0
    fi

    if run_vendor_script "https://astral.sh/uv/install.sh" sh; then
        log_success "uv installed."
    else
        log_error "Failed to install uv. Install it manually: curl -fsSL -o install.sh https://astral.sh/uv/install.sh && sh install.sh"
    fi
}

CARGO_MIN_MINOR=88

cargo_minor_version() {
    local cargo_bin="$1"
    [[ "$(RUSTUP_TOOLCHAIN=stable "$cargo_bin" --version 2>/dev/null)" =~ ^cargo\ 1\.([0-9]+) ]] && echo "${BASH_REMATCH[1]}"
}

cargo_meets_min() {
    local cargo_bin="$1" minor
    minor=$(cargo_minor_version "$cargo_bin")
    (( ${minor:-0} >= CARGO_MIN_MINOR ))
}

install_rustup_toolchain() {
    local rustup="$HOME/.cargo/bin/rustup"
    log_info "No cargo >= 1.$CARGO_MIN_MINOR found; installing a minimal rustup toolchain..."
    if [[ -x "$rustup" ]]; then
        "$rustup" update stable --no-self-update
    else
        run_vendor_script "https://sh.rustup.rs" sh -y --profile minimal --no-modify-path
    fi
}

# Prints only the cargo path: the toolchain install's output goes to stderr so $(...) captures just the path.
# Current cargo-deny and cargo-audit need Rust 1.88; Ubuntu 24.04's apt cargo is 1.75.
cargo_for_crates() {
    local rustup_cargo="$HOME/.cargo/bin/cargo"
    if cargo_meets_min cargo; then
        command -v cargo
        return 0
    fi
    cargo_meets_min "$rustup_cargo" || install_rustup_toolchain >&2 || return 1
    cargo_meets_min "$rustup_cargo" && echo "$rustup_cargo"
}

# Pins the rustup proxy and its rustc to stable, whatever the user's default toolchain is.
run_cargo() {
    local cargo_bin="$1"
    shift
    if [[ "$cargo_bin" == "$HOME/.cargo/bin/cargo" ]]; then
        RUSTUP_TOOLCHAIN=stable PATH="$HOME/.cargo/bin:$PATH" "$cargo_bin" "$@"
    else
        "$cargo_bin" "$@"
    fi
}

# --root ~/.local puts the binary in ~/.local/bin; ~/.cargo/bin is not on PATH.
install_cargo_crate() {
    local crate="$1"
    log_info "Installing $crate..."

    if command -v "$crate" &> /dev/null || [[ -x "$HOME/.local/bin/$crate" ]]; then
        log_info "$crate is already installed. Skipping."
        return 0
    fi

    if [[ "$DRY_RUN" = true ]]; then
        log_dry_run "Would install $crate via cargo install."
        return 0
    fi

    if ! command -v cargo &> /dev/null; then
        log_error "cargo not found; can't install $crate. Add 'cargo' to the preset's package list and re-run, or install manually: cargo install --locked --root ~/.local $crate"
        return 0
    fi

    local cargo_bin
    if ! cargo_bin=$(cargo_for_crates); then
        log_error "No cargo >= 1.$CARGO_MIN_MINOR available for $crate. Install rustup (https://rustup.rs) and re-run, or run: cargo install --locked --root ~/.local $crate"
        return 0
    fi

    if run_cargo "$cargo_bin" install --locked --quiet --root "$HOME/.local" "$crate"; then
        log_success "$crate installed successfully."
    else
        log_error "Failed to install $crate. Install it manually: cargo install --locked --root ~/.local $crate"
    fi
}

install_cargo_deny() { install_cargo_crate cargo-deny; }
install_cargo_audit() { install_cargo_crate cargo-audit; }

ruff_is_installed() { command -v ruff &> /dev/null; }

# No apt candidate and no standalone GitHub-release binary (only Python
# wheels), so this goes through pipx like configure_cozempic_cli rather than
# install_from_url.
install_ruff() {
    log_info "Installing ruff..."

    if ruff_is_installed; then
        log_info "ruff is already installed. Skipping."
        return 0
    fi

    if [[ "$DRY_RUN" = true ]]; then
        log_dry_run "Would install ruff via pipx."
        return 0
    fi

    if ! command -v pipx &> /dev/null; then
        log_error "pipx not found; can't install ruff. Add 'pipx' to packages/apt_common.txt and re-run, or install manually: pipx install ruff"
        return 0
    fi

    if pipx install --quiet ruff; then
        log_success "ruff installed successfully."
    else
        log_error "Failed to install ruff via pipx. Install it manually: pipx install ruff"
    fi
}

AUDITR_VERSION="0.10.5"

auditr_is_installed() { command -v auditr &> /dev/null; }
auditr_is_working() { auditr version &> /dev/null; }

inject_auditr_undeclared_packaging() {
    if ! pipx inject --quiet auditr packaging; then
        log_error "Failed to inject packaging into auditr. Run manually: pipx inject auditr packaging"
        return 0
    fi
    if auditr_is_working; then
        log_success "auditr runtime dependency (packaging) injected."
    else
        log_error "auditr still fails to start after injecting packaging. Diagnose with: auditr version"
    fi
}

install_auditr() {
    log_info "Installing auditr..."

    if auditr_is_installed; then
        if ! auditr_is_working && command -v pipx &> /dev/null && [[ "$DRY_RUN" != true ]]; then
            log_info "auditr is installed but broken; repairing."
            inject_auditr_undeclared_packaging
            return 0
        fi
        log_info "auditr is already installed. Skipping."
        return 0
    fi

    if [[ "$DRY_RUN" = true ]]; then
        log_dry_run "Would install auditr==$AUDITR_VERSION via pipx."
        return 0
    fi

    if ! command -v pipx &> /dev/null; then
        log_error "pipx not found; can't install auditr. Add 'pipx' to packages/apt_common.txt and re-run, or install manually: pipx install auditr==$AUDITR_VERSION"
        return 0
    fi

    if ! python3 -c 'import sys; sys.exit(sys.version_info < (3, 13))' 2> /dev/null; then
        log_error "auditr needs Python >= 3.13 and python3 here is older. Install manually: pipx install --python python3.13 auditr==$AUDITR_VERSION"
        return 0
    fi

    if pipx install --quiet --python python3 "auditr==$AUDITR_VERSION"; then
        log_success "auditr $AUDITR_VERSION installed successfully."
        inject_auditr_undeclared_packaging
    else
        log_error "Failed to install auditr via pipx. Install it manually: pipx install auditr==$AUDITR_VERSION"
    fi
}

