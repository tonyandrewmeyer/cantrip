# VHS tape: cantrip TUI walkthrough.
# Run with: ~/go/bin/vhs demos/recordings/tui.tape

Output "demos/recordings/tui.gif"

Set Shell "bash"
Set FontSize 13
Set Width 1280
Set Height 760
Set Padding 16
Set Theme "Catppuccin Mocha"
Set TypingSpeed 35ms

# Hide the launch line so the GIF starts on the rendered TUI.  Capture
# the cantrip repo root *before* cd-ing so `--project $REPO` resolves
# correctly regardless of where the user keeps their checkout.
Hide
Type "REPO=$(pwd)"
Enter
Sleep 0.3s
Type "cd ~/tui-demo && rm -f .cantrip* && uv run --project $REPO cantrip run . --provider gemini --theme cantrip"
Enter
# Preflight runs against a real Juju controller — give it room.
Sleep 14s
Show

# 1) Pause briefly on the rendered TUI so the layout is readable.
Sleep 3s

# 2) /memory — read-only memory listing.
Type "/memory"
Enter
Sleep 4s

# 3) /cost — token usage and pricing summary.
Type "/cost"
Enter
Sleep 4s

# 4) /diagnostics — ruff/ty/charmlint roll-up for the current charm.
Type "/diagnostics"
Enter
Sleep 4s

# 5) /map — repository map (last because its output is the largest,
#    so nothing else gets pushed out before being seen).
Type "/map"
Enter
Sleep 5s

# 6) Quit cleanly.
Hide
Type "q"
Sleep 0.5s
Show
Sleep 1s
