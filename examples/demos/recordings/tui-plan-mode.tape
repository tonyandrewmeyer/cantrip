# VHS tape: cantrip TUI ``/plan`` mode walkthrough.
#
# Run with: ~/go/bin/vhs demos/recordings/tui-plan-mode.tape
#
# Shows the Phase 68.4 ``/plan`` gate: a read-only mode where the
# agent reads, searches, and proposes designs but cannot edit
# files or run shell commands.  ``/plan`` flips on; the status
# bar tints ``$warning-darken-2`` and badges ``plan mode``.
# ``/build`` flips back.
#
# No LLM call — the visible state change is the status-bar tint.

Output "demos/recordings/tui-plan-mode.gif"

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
Type "cd ~/tui-demo && rm -f .cantrip* && uv run --project $REPO cantrip run . --provider gemini --theme cantrip"
Enter
Sleep 14s
Show

# 1) Pause briefly on the welcome — status bar reads ``DONE``.
Sleep 2s

# 2) Enter plan mode.  The bar tints amber, the badge updates.
Type "/plan"
Enter
Sleep 3s

# 3) Issue a /help to show the chat surface still works under
#    plan mode (read-only commands always work).
Type "/help"
Enter
Sleep 3s

# 4) Leave plan mode.  Bar returns to neutral.
Type "/build"
Enter
Sleep 3s

# 5) Quit cleanly.
Hide
Type "q"
Sleep 0.5s
Show
Sleep 1s
