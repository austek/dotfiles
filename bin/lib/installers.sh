# shellcheck shell=bash
# Sourced by bin/setup.sh — the third-party installers that need a tool from the
# apt step (cargo crates, auditr). The rest live in bin/dotfiles_setup/tools.py.

set -euo pipefail

# Downloads in full before executing so a truncated transfer never runs. Extra args go to the script.
run_vendor_script() {
    local url="$1" shell="$2" script status=0
    shift 2
    script=$(mktemp)
    curl_https -fsSL -o "$script" "$url" && "$shell" "$script" "$@" || status=$?
    rm -f "$script"
    return "$status"
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

