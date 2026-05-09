# VHS tape: cantrip TUI autocomplete popups + help modal.
#
# Run with: ~/go/bin/vhs demos/recordings/tui-popups.tape
#
# This clip complements ``tui.tape`` (which tours the read-only
# slash commands).  It focuses on the inline affordances most
# users discover only by accident: slash-command autocomplete
# (Phase 61 / M61), the ``@``-mention context-provider popup
# (Phase 72 / M72), and the help modal (F1).
#
# The tape uses a dummy provider key — none of the typed input
# triggers an LLM call, so no tokens get burned during a re-run.

Output "demos/recordings/tui-popups.gif"

Set Shell "bash"
Set FontSize 13
Set Width 1280
Set Height 760
Set Padding 16
Set Theme "Catppuccin Mocha"
Set TypingSpeed 50ms

# Hide the launch line so the GIF starts on the rendered TUI.
Hide
Type "REPO=$(pwd)"
Enter
Sleep 0.3s
Type "cd ~/tui-demo && uv run --project $REPO cantrip run . --provider gemini --theme cantrip"
Enter
Sleep 14s
Show

# 1) Welcome — pause briefly so the wordmark + header read.
Sleep 2s

# 2) Slash-command autocomplete (Phase 61).  Type ``/`` to open
#    the popup, then ``c`` to filter to /cost, /clear, /compact.
Type "/"
Sleep 1.5s
Type "c"
Sleep 2s

# 3) Dismiss the popup with Escape; the input clears.
Escape
Sleep 0.5s
Hide
Ctrl+A
Backspace
Show
Sleep 0.5s

# 4) ``@``-mention context provider popup (Phase 72).  Type
#    ``@`` to open the catalogue, then ``do`` to filter to
#    @docs.
Type "@"
Sleep 1.5s
Type "do"
Sleep 2s

# 5) Dismiss and clear.
Escape
Sleep 0.5s
Hide
Ctrl+A
Backspace
Show
Sleep 0.5s

# 6) Help modal (F1) — shows the Phase 108.1 rounded modal frame
#    plus the no-underline section headings.
Type "/help"
Enter
Sleep 4s

# 7) Quit cleanly.
Hide
Type "q"
Sleep 0.5s
Show
Sleep 1s
