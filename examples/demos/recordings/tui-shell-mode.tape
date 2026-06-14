# VHS tape: cantrip TUI shell-mode (Ctrl-X) walkthrough.
#
# Run with: ~/go/bin/vhs demos/recordings/tui-shell-mode.tape
#
# Shows the Phase 69.3 shell-mode affordance: ``Ctrl-X`` toggles
# the input between agent mode and shell mode, the input border
# tints to ``$warning`` so the route change is unmistakable, the
# placeholder updates, and submitted commands render as
# ``$``-prefixed shell blocks rather than LLM messages.
#
# No LLM call — every keystroke routes either to the local
# subprocess (shell mode) or stays in the input buffer.

Output "demos/recordings/tui-shell-mode.gif"

Set Shell "bash"
Set FontSize 13
Set Width 1280
Set Height 760
Set Padding 16
Set Theme "Catppuccin Mocha"
Set TypingSpeed 50ms

# Boot the TUI.  ``rm -f .cantrip*`` clears any prior session
# state so the resume modal does not appear during the recording
# — the existing ``tui.tape`` was originally recorded against a
# fresh charm directory.
Hide
Type "REPO=$(pwd)"
Enter
Sleep 0.3s
Type "cd ~/tui-demo && rm -f .cantrip* && uv run --project $REPO cantrip run . --provider gemini --theme cantrip"
Enter
Sleep 14s
Show

# 1) Pause on the welcome.
Sleep 2s

# 2) Toggle shell mode with Ctrl-X — input border tints amber.
Ctrl+X
Sleep 1.5s

# 3) Run a real shell command.  Output renders as a ``$``-prefixed
#    block in the chat (Phase 69.3 ``add_shell_message``).
Type "ls -la"
Enter
Sleep 3s

# 4) Run another short one to show consecutive shell blocks.
Type "git status -sb"
Enter
Sleep 3s

# 5) Toggle back out — border returns to neutral, agent input
#    placeholder restored.
Ctrl+X
Sleep 2s

# 6) Quit cleanly.
Hide
Type "q"
Sleep 0.5s
Show
Sleep 1s
