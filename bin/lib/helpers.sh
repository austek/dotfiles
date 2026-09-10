# shellcheck shell=bash
# Sourced by bin/setup.sh — generic helpers: existence checks, and the shared
# download/install-from-url pattern used by every third-party binary installer.

set -euo pipefail

command_exists() {
    command -v "$1" >/dev/null 2>&1
}

array_contains() {
    local seeking=$1; shift
    local in=1
    for element; do
        if [[ "$element" == "$seeking" ]]; then
            in=0
            break
        fi
    done
    return $in
}

# Populates $4 from a local cache keyed by $1/$2, downloading $3 into the cache
# on a miss. Sets DOWNLOAD_CACHE_HIT to "true"/"false". Caching is best-effort —
# only the curl step can fail this call; call sites must guard with `if !`.
download_with_cache() {
    local tool="$1" cache_key="$2" url="$3" dest="$4"
    local cache_dir="${XDG_CACHE_HOME:-$HOME/.cache}/dotfiles-setup/$tool"
    mkdir -p "$cache_dir" 2>/dev/null || true
    local cached_file="$cache_dir/$cache_key"

    if [ -s "$cached_file" ] && cp -- "$cached_file" "$dest" 2>/dev/null; then
        DOWNLOAD_CACHE_HIT=true
        return 0
    fi

    DOWNLOAD_CACHE_HIT=false
    if ! curl -sL -o "$dest" "$url"; then
        return 1
    fi

    # Write-then-rename so an interrupted run never leaves a corrupt cache entry.
    if cp -- "$dest" "$cache_dir/.$cache_key.tmp" 2>/dev/null; then
        mv -f -- "$cache_dir/.$cache_key.tmp" "$cached_file" 2>/dev/null || true
        find "$cache_dir" -maxdepth 1 -type f ! -name "$cache_key" ! -name '.*' -delete 2>/dev/null || true
    fi
    return 0
}

# Generic download-install flow shared by the six URL-based installers.
# NAME is a display string; CHECK_FN/RESOLVE_FN/INSTALL_FN are function
# names invoked indirectly (never eval'd); EXTRACT_KIND is one of
# targz|zip|deb. RESOLVE_FN prints "version\turl\tcache_key" on stdout
# (version may be empty) and returns non-zero if resolution fails.
# INSTALL_FN is called as INSTALL_FN "$temp_dir" "$version" "$artifact_path".
install_from_url() {
    local name="$1" check_fn="$2" resolve_fn="$3" extract_kind="$4" install_fn="$5"

    log_info "Installing $name..."

    if "$check_fn"; then
        log_info "$name is already installed. Skipping."
        return 0
    fi

    if [ "$DRY_RUN" = true ]; then
        log_dry_run "Would fetch $name latest release"
        log_dry_run "Would download and install $name"
        return 0
    fi

    local resolved
    if ! resolved=$("$resolve_fn"); then
        log_error "Failed to resolve $name download URL."
        log_warn "Continuing with setup..."
        return 0
    fi
    local version url cache_key rest
    version="${resolved%%$'\t'*}"
    rest="${resolved#*$'\t'}"
    url="${rest%%$'\t'*}"
    cache_key="${rest#*$'\t'}"

    local temp_dir
    temp_dir=$(mktemp -d)
    register_temp_dir "$temp_dir"
    # Self-clearing: a RETURN trap set here also re-fires once in the
    # immediate caller's frame (e.g. the one-line install_x wrapper), where
    # $temp_dir is unbound under `set -u`. Clear it after first use.
    trap 'rm -rf -- "$temp_dir"; trap - RETURN' RETURN

    local artifact_path="$temp_dir/artifact"
    log_info "Fetching $name${version:+ v$version}..."
    if ! download_with_cache "$name" "$cache_key" "$url" "$artifact_path"; then
        log_error "Failed to download $name from $url"
        log_warn "Continuing with setup..."
        return 0
    fi
    [ "$DOWNLOAD_CACHE_HIT" = true ] && log_info "(using cached download)"

    case "$extract_kind" in
        targz)
            if ! tar xf "$artifact_path" -C "$temp_dir"; then
                log_error "Failed to extract $name from tarball."
                log_warn "Continuing with setup..."
                return 0
            fi
            ;;
        zip)
            if ! unzip -q "$artifact_path" -d "$temp_dir"; then
                log_error "Failed to extract $name installer."
                log_warn "Continuing with setup..."
                return 0
            fi
            ;;
        deb)
            : # install_fn handles dpkg -i directly against the raw artifact_path
            ;;
    esac

    if ! "$install_fn" "$temp_dir" "$version" "$artifact_path"; then
        log_error "Failed to install $name."
        log_warn "Continuing with setup..."
        return 0
    fi

    log_success "$name installed successfully${version:+ v$version}."
}

# Shared by zoom's and slack's install steps.
install_deb_or_fix_broken() {
    local deb_path="$1" dpkg_grep_pattern="$2"
    if quiet_run sudo dpkg -i "$deb_path"; then
        return 0
    fi
    log_warn "dpkg reported errors. Running 'apt --fix-broken install'..."
    quiet_run sudo apt-get -y --fix-broken install
    dpkg -l | grep -q "^ii.*$dpkg_grep_pattern"
}

