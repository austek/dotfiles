[[ -r "$HOME/.cargo/env" ]] && . "$HOME/.cargo/env"
export DENGJEN_ESPEAKNG_DATA_DIRECTORY=${DENGJEN_ESPEAKNG_DATA_DIRECTORY:-/usr/lib/x86_64-linux-gnu}

# PATH lives here, not in .zshrc, so non-interactive shells (IDE-launched agents) get it.
# The list itself is packages/path_dirs.txt plus the overlay's packages/path_dirs_extra.txt; Claude's env.PATH
# and the foothold unit render from the same files. typeset -U keeps entries unique across nested shells.
typeset -U path PATH
path=( ${^path}(N-/) )

# Mirrors overlay.find_overlay_root: a set variable wins even when its directory is missing (no overlay).
_dotfiles_overlay_root() {
    local variable candidate
    for variable in DOTFILES_OVERLAY_ROOT DOTFILES_PRIVATE_ROOT; do
        if [[ -n ${(P)variable} ]]; then
            [[ -d ${(P)variable} ]] && REPLY=${(P)variable} || REPLY=''
            return
        fi
    done
    REPLY=''
    for candidate in "$HOME/.dotfiles-overlay" "$HOME/.dotfiles-private" "$HOME/.config/dotfiles/local-overlay"; do
        [[ -d $candidate ]] && { REPLY=$candidate; return }
    done
}

# Sets `reply` to the absolute directories one list file names; a relative entry is skipped so a directory
# named `bin` never resolves against the working directory.
_dotfiles_path_file() {
    emulate -L zsh
    setopt extendedglob
    local line entry
    reply=()
    [[ -r $1 ]] || return 0
    for line in "${(@f)$(<$1)}"; do
        entry=${${line##[[:space:]]##}%%[[:space:]]##}
        [[ -z $entry || $entry == '#'* ]] && continue
        entry=${entry/#\~\//$HOME/}
        [[ $entry == /* ]] && reply+=( $entry )
    done
}

# A candidate the inherited PATH already selects (sdk use, a venv, a parent shell) keeps its place: the list's
# user directories come first, inherited entries the list does not name follow them, and the list's system
# directories and everything after come last. A listed sdkman `current` entry is dropped when the inherited
# PATH already has a version of that tool.
_dotfiles_path_list() {
    emulate -L zsh
    local entry tool root
    local -a listed=() base_entries=() extras=()
    _dotfiles_path_file "$HOME/.dotfiles/packages/path_dirs.txt"
    base_entries=( $reply )
    (( $#base_entries )) || base_entries=( "$HOME/.dotfiles/bin" "$HOME/bin" "$HOME/.local/bin" )
    _dotfiles_overlay_root
    root=$REPLY
    [[ -n $root ]] && { _dotfiles_path_file "$root/packages/path_dirs_extra.txt"; extras=( $reply ) }
    for entry in $base_entries $extras; do
        if [[ $entry == $HOME/.sdkman/candidates/*/current/bin ]]; then
            tool=${${entry#$HOME/.sdkman/candidates/}%%/*}
            (( ${path[(I)$HOME/.sdkman/candidates/$tool/*]} )) && continue
        fi
        listed+=( $entry )
    done
    local -i split=$(( $#listed + 1 )) index
    for (( index = 1; index <= $#listed; index++ )); do
        [[ $listed[index] == $HOME/* ]] || { split=index; break }
    done
    path=( ${listed[1,split-1]} ${path:|listed} ${listed[split,-1]} )
}

_dotfiles_path_list
path=( ${^path}(N-/) )
unfunction _dotfiles_path_list _dotfiles_path_file _dotfiles_overlay_root
