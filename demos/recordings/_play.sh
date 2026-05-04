#!/usr/bin/env bash
# Helpers for asciinema-friendly clip scripts. Source with:
#   . "$(dirname "$0")/_play.sh"
#
# Functions:
#   PROMPT          render "$ " in a colour matching most asciinema themes
#   typewrite CMD   print CMD with a typing effect, then a newline
#   run     CMD     typewrite CMD, then run it via bash -c (so pipes/redirects work)
#   pause   [SEC]   sleep, default 1.2s — good for letting the viewer read output
#   note    TEXT    render TEXT prefixed with "# " (commentary)

# Tune typing speed via env vars when iterating.
TYPE_DELAY="${TYPE_DELAY:-0.025}"
PROMPT_PAUSE="${PROMPT_PAUSE:-0.6}"
DEFAULT_PAUSE="${DEFAULT_PAUSE:-1.2}"

PROMPT() { printf "\033[1;32m$ \033[0m"; }

typewrite() {
    local s="$1"
    local i ch
    for (( i=0; i<${#s}; i++ )); do
        ch="${s:$i:1}"
        printf '%s' "$ch"
        sleep "$TYPE_DELAY"
    done
    printf '\n'
}

run() {
    PROMPT
    typewrite "$1"
    sleep "$PROMPT_PAUSE"
    bash -c "$1"
}

pause() {
    sleep "${1:-$DEFAULT_PAUSE}"
}

note() {
    printf "\033[2;37m# %s\033[0m\n" "$1"
}
