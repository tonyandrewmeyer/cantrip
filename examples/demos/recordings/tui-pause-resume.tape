# VHS tape: cantrip TUI ``/pause`` and ``/resume``.
#
# Run with: ~/go/bin/vhs demos/recordings/tui-pause-resume.tape
#
# Shows the Phase 99.1 lifecycle commands: ``/pause`` stops the
# autonomous loop from picking new tasks (the chat keeps working
# and any in-flight CONFIRM tasks finish); ``/resume`` flips the
# loop back on.  The status bar's lifecycle badge follows the
# state — ``PAUSED`` while paused (``$warning-darken-1`` tint),
# and the badge clears when the loop is back to RUNNING.
#
# No LLM call — both commands flip a state flag that the bus
# pushes into the status-bar reactive.

Output "demos/recordings/tui-pause-resume.gif"

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

# 1) Pause briefly on the welcome.
Sleep 2s

# 2) Pause the autonomous loop.  Status bar tints; ``PAUSED``
#    badge appears.
Type "/pause"
Enter
Sleep 4s

# 3) Resume — the badge clears, the bar returns to neutral.
Type "/resume"
Enter
Sleep 4s

# 4) Quit cleanly.
Hide
Type "q"
Sleep 0.5s
Show
Sleep 1s
