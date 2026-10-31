# Path to your dotfiles.
export DOTFILES=$HOME/.dotfiles

# Path to your oh-my-zsh installation.
export ZSH="$HOME/.oh-my-zsh"

ZSH_THEME="robbyrussell"

HIST_STAMPS="yyyy-mm-dd"
setopt HIST_IGNORE_DUPS
setopt HIST_IGNORE_ALL_DUPS
setopt HIST_IGNORE_SPACE
setopt HIST_REDUCE_BLANKS
setopt HIST_SAVE_NO_DUPS
setopt HIST_FIND_NO_DUPS

# The trailing (| *) makes each entry match bare or with arguments, but not prefixes: ls is ignored, lsof is saved.
HISTORY_IGNORE='(git reset*|git status|git log|git diff|git branch|reboot|shutdown|cat|cd|cp|echo|exit|export|history|less|ll|ln|ls|man|mkdir|mv|ps|pwd|rm|tail|head|multitail|tar|tree|touch|unzip|wc|wget|whence|where|which|zip|apt|apt-get|dpkg|pacman|clear|df|du|free|ping|dig|nslookup|ip|ifconfig|netstat|ss|nmap|lsusb|lsmod|lspci|dmidecode|glxinfo|kill|killall|source|deactivate|claude --resume*|claude-burst --resume*|chmod *|..|~)(| *)'

plugins=(
  1password
  aliases
  alias-finder
  cp
  docker
  gh
  git
  gradle
  k9s
  kubectl
  kubectx
  man
  minikube
  node
  npm
  nvm
  ssh
  ssh-agent
  sudo
  ubuntu
  vscode
  zsh-autosuggestions
  zsh-syntax-highlighting
)

fpath=(~/.config/zsh/completions "${fpath[@]}")

source $ZSH/oh-my-zsh.sh

export EDITOR='nano'
export VISUAL="antigravity-ide --wait"

export RTK_TELEMETRY_DISABLED=1     # telemetry is opt-in already; belt-and-suspenders
unset RTK_TRUST_PROJECT_FILTERS     # never let a repo's build files flip the trust bypass
unset RTK_TEE_DIR                   # use the default; avoids path-traversal footguns
# Do NOT set RTK_SKIP_CHECKSUM

# --- NEW FUNCTION LOADING ---
fpath=( ~/.config/zsh/functions "${fpath[@]}" )

autoload -Uz $fpath[1]/*(:t)
# --- END NEW FUNCTION LOADING ---

# --- PATH ---
# Must follow the autoload block above: path_prepend/path_append live in $fpath.
# typeset -U keeps entries unique, so nested shells can't accumulate duplicates.
typeset -U path PATH
path_prepend "$HOME/.local/bin"
path_prepend "$HOME/bin"
path_prepend "$HOME/.dotfiles/bin"
path_append "$HOME/.local/share/JetBrains/Toolbox/bin" "$HOME/.local/share/JetBrains/Toolbox/scripts"
path_append "$HOME/.krew/bin"
path_append "/usr/local/go/bin"
# --- END PATH ---

alias claude='claude-tmux main claude'

# --- LOAD SECRET/MANUAL OVERRIDES ---
# Optional shell-only overrides (aliases, functions). Env-var secrets belong in ~/.config/dotfiles/secrets.env.
# It is NOT in the git repo.
if [[ -r ~/.zshrc.secret ]]; then
  source ~/.zshrc.secret
fi
# --- END SECRET/MANUAL OVERRIDES ---

# --- SECRET ENV VARS ---
# Plain KEY=value lines, shared with the claude-foothold systemd unit (EnvironmentFile).
if [[ -r ~/.config/dotfiles/secrets.env ]]; then
  zmodload -F zsh/stat b:zstat
  if (( ($(zstat +mode ~/.config/dotfiles/secrets.env) & 8#077) == 0 )); then
    set -a
    source ~/.config/dotfiles/secrets.env
    set +a
  else
    print -u2 "secrets.env skipped: group/other can access it; run chmod 600 ~/.config/dotfiles/secrets.env"
  fi
fi
# --- END SECRET ENV VARS ---

# --- DIRENV ---
# Must follow the secrets blocks so .envrc values (e.g. SONARQUBE_CLI_ORG) win.
if (( $+commands[direnv] )); then
  eval "$(direnv hook zsh)"
fi
# --- END DIRENV ---

if grep -q "0x1002" /sys/class/drm/card*/device/vendor(N) /dev/null 2>/dev/null; then
  export RUSTICL_ENABLE=radeonsi
fi

if [[ -r $HOME/.nvm ]]; then
    export NVM_DIR="$HOME/.nvm"
    [ -s "$NVM_DIR/nvm.sh" ] && \. "$NVM_DIR/nvm.sh"
    [ -s "$NVM_DIR/bash_completion" ] && \. "$NVM_DIR/bash_completion"
fi

if [[ -d $HOME/.local/share/pnpm ]]; then
    export PNPM_HOME="$HOME/.local/share/pnpm"
    path_prepend "$PNPM_HOME"
fi

#THIS MUST BE AT THE END OF THE FILE FOR SDKMAN TO WORK!!!
if [[ -r $HOME/.sdkman ]]; then
    export SDKMAN_DIR="$HOME/.sdkman"
    [[ -s "$HOME/.sdkman/bin/sdkman-init.sh" ]] && source "$HOME/.sdkman/bin/sdkman-init.sh"
fi

path_prepend "$HOME/.local/share/sonarqube-cli/bin"

path_prepend "$HOME/.opencode/bin"
