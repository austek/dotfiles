[[ -r "$HOME/.cargo/env" ]] && . "$HOME/.cargo/env"
export DENGJEN_ESPEAKNG_DATA_DIRECTORY=${DENGJEN_ESPEAKNG_DATA_DIRECTORY:-/usr/lib/x86_64-linux-gnu}

# PATH lives here, not in .zshrc, so non-interactive shells (IDE-launched agents) get it.
# The list itself is packages/path_dirs.txt plus the overlay's packages/path_dirs_extra.txt; Claude's env.PATH
# and the foothold unit render from the same files. typeset -U keeps entries unique across nested shells.
typeset -U path PATH
path=( ${^path}(N-/) )

# Sets `reply` to the listed directories. A candidate the inherited PATH already selects (sdk use, a parent
# shell) keeps that version, so the list's `current` entry for that sdkman tool is dropped.
_dotfiles_path_list() {
    emulate -L zsh
    setopt extendedglob
    local file line entry tool
    reply=()
    for file in "$HOME/.dotfiles/packages/path_dirs.txt" \
                "${DOTFILES_OVERLAY_ROOT:-$HOME/.dotfiles-overlay}/packages/path_dirs_extra.txt"; do
        [[ -r $file ]] || continue
        for line in "${(@f)$(<$file)}"; do
            entry=${${line##[[:space:]]##}%%[[:space:]]##}
            [[ -z $entry || $entry == '#'* ]] && continue
            entry=${entry/#\~\//$HOME/}
            if [[ $entry == $HOME/.sdkman/candidates/*/current/bin ]]; then
                tool=${${entry#$HOME/.sdkman/candidates/}%%/*}
                (( ${path[(I)$HOME/.sdkman/candidates/$tool/*]} )) && continue
            fi
            reply+=( $entry )
        done
    done
}

_dotfiles_path_list
(( $#reply )) || reply=( "$HOME/.dotfiles/bin" "$HOME/bin" "$HOME/.local/bin" )
path=( $reply $path )
path=( ${^path}(N-/) )
unset reply
unfunction _dotfiles_path_list
