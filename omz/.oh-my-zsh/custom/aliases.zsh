alias paths='echo $PATH | tr ":" "\n"'
alias ucase="tr '[:lower:]' '[:upper:]'"
alias lcase="tr '[:upper:]' '[:lower:]'"

if command -v pbcopy >/dev/null 2>&1; then
    :
elif [ -n "$WAYLAND_DISPLAY" ] && command -v wl-copy >/dev/null 2>&1; then
    alias pbcopy='wl-copy'
    alias pbpaste='wl-paste'
elif [ -n "$DISPLAY" ] && command -v xclip >/dev/null 2>&1; then
    alias pbcopy='xclip -selection clipboard'
    alias pbpaste='xclip -selection clipboard -o'
elif [ -n "$DISPLAY" ] && command -v xsel >/dev/null 2>&1; then
    alias pbcopy='xsel --clipboard --input'
    alias pbpaste='xsel --clipboard --output'
fi

alias ll='ls -la'
alias k="kubectl"
alias kctx="kubectx"
alias kns="kubens"
alias gw='./gradlew'
alias staywake='systemd-inhibit --what=sleep --why="active ssh session" --mode=block sleep infinity &'
