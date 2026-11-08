. "$HOME/.cargo/env"
export DENGJEN_ESPEAKNG_DATA_DIRECTORY=/usr/lib/x86_64-linux-gnu

# PATH lives here, not in .zshrc, so non-interactive shells (IDE-launched agents) get it.
# typeset -U keeps entries unique across nested shells.
typeset -U path PATH
path=(
    "$HOME/.local/share/sonarqube-cli/bin"
    "$HOME/.sdkman/candidates/sbt/current/bin"
    "$HOME/.sdkman/candidates/kotlin/current/bin"
    "$HOME/.sdkman/candidates/gradle/current/bin"
    "$HOME/.dotfiles/bin"
    "$HOME/bin"
    "$HOME/.local/bin"
    "$HOME/.sdkman/candidates/java/current/bin"
    $path
    "$HOME/.local/share/JetBrains/Toolbox/bin"
    "$HOME/.local/share/JetBrains/Toolbox/scripts"
    "$HOME/.krew/bin"
    /usr/local/go/bin
)
path=( ${^path}(N-/) )
