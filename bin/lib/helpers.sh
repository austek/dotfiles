# shellcheck shell=bash
# shellcheck disable=SC2034  # DOWNLOAD_CACHE_HIT is read by apt.sh
# Sourced by bin/setup.sh — generic helpers: existence checks and the download cache.

set -euo pipefail

command_exists() {
    local name="$1"
    command -v "$name" >/dev/null 2>&1
}

curl_https() {
    curl --proto '=https' "$@"
}

print_resolved() {
    local version="$1" url="$2" cache_key="$3"
    printf '%s\t%s\t%s\n' "$version" "$url" "$cache_key"
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

    if [[ -s "$cached_file" ]] && cp -- "$cached_file" "$dest" 2>/dev/null; then
        DOWNLOAD_CACHE_HIT=true
        return 0
    fi

    DOWNLOAD_CACHE_HIT=false
    if ! curl_https -fsSL -o "$dest" "$url"; then
        return 1
    fi

    # Write-then-rename so an interrupted run never leaves a corrupt cache entry.
    if cp -- "$dest" "$cache_dir/.$cache_key.tmp" 2>/dev/null; then
        mv -f -- "$cache_dir/.$cache_key.tmp" "$cached_file" 2>/dev/null || true
        find "$cache_dir" -maxdepth 1 -type f ! -name "$cache_key" ! -name '.*' -delete 2>/dev/null || true
    fi
    return 0
}

