# Path to your dotfiles.
export DOTFILES=$HOME/.dotfiles

# If you come from bash you might have to change your $PATH.
# export PATH=$HOME/bin:/usr/local/bin:$PATH

# Path to your oh-my-zsh installation.
export ZSH="$HOME/.oh-my-zsh"

# Minimal - Theme Settings
export MNML_INSERT_CHAR="$"
export MNML_PROMPT=(mnml_git mnml_keymap)
export MNML_RPROMPT=('mnml_cwd 20')

# Set name of the theme to load --- if set to "random", it will
# load a random theme each time oh-my-zsh is loaded, in which case,
# to know which specific one was loaded, run: echo $RANDOM_THEME
# See https://github.com/ohmyzsh/ohmyzsh/wiki/Themes
ZSH_THEME="robbyrussell"

# Set list of themes to pick from when loading at random
# Setting this variable when ZSH_THEME=random will cause zsh to load
# a theme from this variable instead of looking in $ZSH/themes/
# If set to an empty array, this variable will have no effect.
# ZSH_THEME_RANDOM_CANDIDATES=( "robbyrussell" "agnoster" "powerlevel10k/powerlevel10k")

# Uncomment the following line to use case-sensitive completion.
# CASE_SENSITIVE="true"

# Uncomment the following line to use hyphen-insensitive completion.
# Case-sensitive completion must be off. _ and - will be interchangeable.
# HYPHEN_INSENSITIVE="true"

# Uncomment one of the following lines to change the auto-update behavior
# zstyle ':omz:update' mode disabled  # disable automatic updates
# zstyle ':omz:update' mode auto      # update automatically without asking
# zstyle ':omz:update' mode reminder  # just remind me to update when it's time

# Uncomment the following line to change how often to auto-update (in days).
# zstyle ':omz:update' frequency 13

# Uncomment the following line if pasting URLs and other text is messed up.
# DISABLE_MAGIC_FUNCTIONS="true"

# Uncomment the following line to disable colors in ls.
# DISABLE_LS_COLORS="true"

# Uncomment the following line to disable auto-setting terminal title.
# DISABLE_AUTO_TITLE="true"

# Uncomment the following line to enable command auto-correction.
# ENABLE_CORRECTION="true"

# Uncomment the following line to display red dots whilst waiting for completion.
# You can also set it to another string to have that shown instead of the default red dots.
# e.g. COMPLETION_WAITING_DOTS="%F{yellow}waiting...%f"
# Caution: this setting can cause issues with multiline prompts in zsh < 5.7.1 (see #5765)
# COMPLETION_WAITING_DOTS="true"

# Uncomment the following line if you want to disable marking untracked files
# under VCS as dirty. This makes repository status check for large repositories
# much, much faster.
# DISABLE_UNTRACKED_FILES_DIRTY="true"

# Uncomment the following line if you want to change the command execution time
# stamp shown in the history command output.
# You can set one of the optional three formats:
# "mm/dd/yyyy"|"dd.mm.yyyy"|"yyyy-mm-dd"
# or set a custom format using the strftime function format specifications,
# see 'man strftime' for details.
HIST_STAMPS="yyyy-mm-dd"
#setopt HIST_EXPIRE_DUPS_FIRST
setopt HIST_IGNORE_DUPS
setopt HIST_IGNORE_ALL_DUPS
setopt HIST_IGNORE_SPACE
#setopt HIST_FIND_NO_DUPS
#setopt HIST_SAVE_NO_DUPS

export HIST_IGNORE_PATTERN='(git reset*|reboot|shutdown|cat|cd|cp|echo|exit|export|history|less|ll|ln|ls|man|mkdir|mv|ps|pwd|rm|tail|tree|where|which|..|~)'

# Would you like to use another custom folder than $ZSH/custom?
# ZSH_CUSTOM=$DOTFILES/omz/custom

# Which plugins would you like to load?
# Standard plugins can be found in $ZSH/plugins/
# Custom plugins may be added to $ZSH_CUSTOM/plugins/
# Example format: plugins=(rails git textmate ruby lighthouse)
# Add wisely, as too many plugins slow down shell startup.
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

# User configuration

# export MANPATH="/usr/local/man:$MANPATH"

# You may need to manually set your language environment
# export LC_ALL=en_GB.UTF-8
# export LANG=en_GB.UTF-8

# Preferred editor for local and remote sessions
export EDITOR='nano'
export VISUAL="antigravity-ide --wait"
# if [[ -n $SSH_CONNECTION ]]; then
#   export EDITOR='vim'
# else
#   export EDITOR='mvim'
# fi

# Compilation flags
# export ARCHFLAGS="-arch $(uname -m)"

# Set personal aliases, overriding those provided by oh-my-zsh libs,
# plugins, and themes. Aliases can be placed here, though oh-my-zsh
# users are encouraged to define aliases within a top-level file in
# the $ZSH_CUSTOM folder, with .zsh extension. Examples:
# - $ZSH_CUSTOM/aliases.zsh
# - $ZSH_CUSTOM/macos.zsh
# For a full list of active aliases, run `alias`.
#
# Example aliases
# alias zshconfig="mate ~/.zshrc"
# alias ohmyzsh="mate ~/.oh-my-zsh"

export RTK_TELEMETRY_DISABLED=1     # telemetry is opt-in already; belt-and-suspenders
unset RTK_TRUST_PROJECT_FILTERS     # never let a repo's build files flip the trust bypass
unset RTK_TEE_DIR                   # use the default; avoids path-traversal footguns
# Do NOT set RTK_SKIP_CHECKSUM

export DD_MCP_DOMAIN=mcp.datadoghq.com     # Datadog Claude Code plugin MCP server site

# To customize prompt, run `p10k configure` or edit ~/.p10k.zsh.

# --- NEW FUNCTION LOADING ---
fpath=( ~/.config/zsh/functions "${fpath[@]}" )

# Note: 'paths' is an alias in ~/.oh-my-zsh/custom/aliases.zsh
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

# --- LOAD PROFILE CONFIGS ---
# This file is built by setup.sh from ~/dotfiles/profiles
# It is ignored by .gitignore
if [[ -r ~/.zshrc.profile ]]; then
  source ~/.zshrc.profile
fi
# --- END PROFILE CONFIGS ---

# --- LOAD SECRET/MANUAL OVERRIDES ---
# This file is for manual, machine-specific, or secret configs (e.g. API keys).
# It is NOT in the git repo.
if [[ -r ~/.zshrc.secret ]]; then
  source ~/.zshrc.secret
fi
# --- END SECRET/MANUAL OVERRIDES ---

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

# Added by sonarqube-cli installer
path_prepend "$HOME/.local/share/sonarqube-cli/bin"

path_prepend "$HOME/.opencode/bin"
