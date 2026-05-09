# VHS tape: cantrip TUI ``/feelings`` parliament walkthrough.
#
# Run with: ~/go/bin/vhs demos/recordings/tui-feelings.tape
#
# Shows Phase 87.1 ``/feelings``: the inner parliament — Inside
# Out-style — convenes ``joy`` and ``fear`` (the two-emotion
# default) and produces a markdown summary of how the agent
# would advise the user given the current charm state.
#
# Runs against a real charm under ``$HOME/broken-charm`` (a
# deliberately incomplete charm originally staged for the
# ``--improve`` audit demo).  The richer the charm, the more the
# parliament has to argue about — joy spots strengths, fear
# spots risks.
#
# Cost: 2 LLM calls per run (joy + fear); each is a short
# system-prompt + state digest, so the bill is small.

Output "demos/recordings/tui-feelings.gif"

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
Type "cd ~/broken-charm && rm -f .cantrip* && uv run --project $REPO cantrip run . --provider gemini --theme cantrip"
Enter
Sleep 14s
Show

# 1) Pause briefly on the welcome — ``broken-charm`` shows in
#    the header path; the file tree on the right reflects it.
Sleep 2s

# 2) Convene the parliament.  Joy and fear deliberate; the
#    summary lands as a system message that renders as Markdown
#    (Phase 108.6 timestamp suppressed because the previous
#    chip is still inside the gap window).
Type "/feelings"
Enter
Sleep 35s

# 3) Quit cleanly.
Hide
Type "q"
Sleep 0.5s
Show
Sleep 1s
