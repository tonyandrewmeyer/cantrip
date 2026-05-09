# VHS tape: cantrip TUI ``--yolo`` mode walkthrough.
#
# Run with: ~/go/bin/vhs demos/recordings/tui-yolo-mode.tape
#
# Shows the Phase 69.2 ``--yolo`` startup flag: confirmations are
# disabled, the agent acts on its own design proposals, and the
# status bar tints ``$error-darken-1`` with a ``YOLO MODE —
# confirmations off`` badge so the elevated trust is impossible
# to miss.
#
# No LLM call — the visible state change is the status-bar tint.

Output "demos/recordings/tui-yolo-mode.gif"

Set Shell "bash"
Set FontSize 13
Set Width 1280
Set Height 760
Set Padding 16
Set Theme "Catppuccin Mocha"
Set TypingSpeed 50ms

Hide
Type "REPO=$(pwd)"
Enter
Sleep 0.3s
Type "cd ~/tui-demo && rm -f .cantrip* && uv run --project $REPO cantrip run . --provider gemini --theme cantrip --yolo"
Enter
Sleep 14s
Show

# 1) Pause on the welcome — status bar shows the YOLO MODE badge
#    in red.
Sleep 4s

# 2) Issue a /help to confirm the chat surface still works under
#    yolo mode.  The badge stays prominent across slash-command
#    output so users cannot forget the elevated trust setting.
Type "/help"
Enter
Sleep 4s

# 3) Quit cleanly.
Hide
Type "q"
Sleep 0.5s
Show
Sleep 1s
