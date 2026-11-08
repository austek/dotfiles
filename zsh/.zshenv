[[ -r "$HOME/.cargo/env" ]] && . "$HOME/.cargo/env"
export DENGJEN_ESPEAKNG_DATA_DIRECTORY=/usr/lib/x86_64-linux-gnu

# PATH lives here, not in .zshrc, so non-interactive shells (IDE-launched agents) get it.
# typeset -U keeps entries unique across nested shells.
typeset -U path PATH
# A candidate the inherited PATH already selects (sdk use, a parent shell) keeps that version.
typeset -a sdkman_default=()
typeset sdkman_tool=''
for sdkman_tool in sbt kotlin gradle java; do
    (( ${path[(I)$HOME/.sdkman/candidates/$sdkman_tool/*]} )) \
        || sdkman_default+=("$HOME/.sdkman/candidates/$sdkman_tool/current/bin")
done
path=(
    "$HOME/.local/share/sonarqube-cli/bin"
    $sdkman_default
    "$HOME/.dotfiles/bin"
    "$HOME/bin"
    "$HOME/.local/bin"
    $path
    "$HOME/.local/share/JetBrains/Toolbox/bin"
    "$HOME/.local/share/JetBrains/Toolbox/scripts"
    "$HOME/.krew/bin"
    /usr/local/go/bin
)
path=( ${^path}(N-/) )
unset sdkman_default sdkman_tool
