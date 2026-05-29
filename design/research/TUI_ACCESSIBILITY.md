# TUI Accessibility

Cantrip's TUI is a [Textual](https://textual.textualize.io/) application.
This note documents what Cantrip does to keep the TUI accessible,
where the boundary between automated coverage and manual testing
sits, and how a maintainer should verify accessibility before a
release.

The Web UI has a separate, more comprehensive audit in
[`WEB_UI_ACCESSIBILITY_AUDIT.md`](./WEB_UI_ACCESSIBILITY_AUDIT.md)
backed by integration tests in
`tests/integration/web/test_accessibility.py`.  The web surface can
target WCAG 2.1 AA directly; the TUI surface cannot, because a
terminal-emulated UI's accessibility depends on the user's terminal
emulator, their screen reader, and the bridges between them.  The
goal here is **not** WCAG conformance — it is *don't make Textual's
own accessibility surface worse than it is by default*.

## What "accessible" means for a Textual app

A blind or low-vision developer reaches a Textual app through one of
two routes today:

1. **A screen reader narrating the terminal's accessibility tree.**
   macOS + Terminal.app + VoiceOver and Windows + Windows Terminal +
   NVDA both expose terminal content via the OS accessibility APIs.
   Textual emits structured content (widget roles, focus, text) that
   these screen readers can read — but the path is *narrate the
   terminal*, not *narrate the Textual widget tree directly*.
2. **Braille / refreshable braille displays via terminal bridges.**
   Same story: the bridge reads whatever the terminal emulator
   exposes.

This means TUI accessibility is mostly about three things, in
descending order of leverage:

1. **Keyboard navigation completeness.**  Every action a sighted
   mouse user can take must also be reachable from the keyboard.
   This is the single biggest accessibility lever for a TUI; if the
   keyboard works, the screen reader has something to narrate.
2. **Text-first content.**  Status, decisions, and prose must not
   depend on colour or glyph alone — the *text* of a widget has to
   carry the meaning.  Colour is a redundant cue.
3. **Predictable focus.**  When a screen opens, focus lands on the
   primary control; when a screen closes, focus returns to where it
   came from.  Without this, screen-reader users lose their place
   between every modal.

## What Cantrip already does well

- **Every action has a keyboard binding.**  The App and every Screen
  subclass declare a `BINDINGS` list; the
  [`Footer`](https://textual.textualize.io/widgets/footer/) renders
  them at the bottom of the screen.  Mouse-only paths are
  deliberately avoided.
- **The Footer is structurally present.**  Even if a terminal /
  screen reader misses individual binding hints, the Footer can be
  reflowed and re-read.  See Phase 93.1 — the modal footer hints
  bug (Rich markup eating `[…]`) was fixed precisely because the
  footer is the keyboard-accessibility surface.
- **Bindings are described.**  The third argument to `Binding(key,
  action, description)` is the human-readable label; the smoke test
  in `tests/unit/tui/test_accessibility_smoke.py` enforces that
  every shown binding has one.
- **Status carries text, not just colour.**  The status bar names
  the active phase (`build · 11`), the task chip, and progress
  counters in words.  Colour is a redundant cue (Phase 108 visual
  refresh).
- **Cancel / Escape is consistent.**  `Escape` cancels the current
  agent turn from anywhere; modals dismiss with `Escape`.  No
  modal traps the user.

## Known gaps and how we handle them

- **F-keys.**  The primary screens are bound to F1–F9.  Many
  terminals (Terminal.app, screen-reader–mediated sessions, remote
  SSH chains through restrictive PTYs) intercept the F-row before
  Textual sees it.  The mitigation today is *every F-key has an
  equivalent slash command* (`/help`, `/logs`, `/transcript`,
  `/files`, `/graph`, …) so a user with F-keys captured can still
  reach every screen.  See `src/cantrip/agent/commands/`.
- **Tool-block colour status cues.**  Tool intro / post captions use
  colour to indicate success / failure / running.  The text label
  (`▸ read …`, `✓`, `✗`, `running…`) also carries the state, so a
  colour-blind or screen-reader user can still read what happened.
- **Streaming reasoning panes.**  Extended-thinking previews
  collapse to a single-line summary by default; they aren't
  auto-expanded, so a screen reader doesn't re-read a token stream
  every tick.
- **Right-pane file tree.**  Selecting a node fires a screen with
  enough text for the active item; the tree itself is navigable by
  arrow keys.

## What's automated

Two automated checks ship today:

1. **Web UI** — Live-browser integration tests under
   `tests/integration/web/test_accessibility.py` cover ARIA roles,
   labelled controls, overlay-as-dialog semantics, focus management,
   and computed contrast for the primary controls.  These run when
   `uvx rodney` and Chromium are available; they skip cleanly
   otherwise.
2. **TUI keyboard surface** — `tests/unit/tui/test_accessibility_smoke.py`
   walks every Textual `BINDINGS` list (the App and every Screen
   subclass under `src/cantrip/tui/screens/`) and asserts:
   - every shown binding has a non-empty description,
   - every binding's `action` resolves to a callable on the App /
     Screen class (a `action_<name>` method, a Textual built-in
     like `dismiss` / `quit`, or an explicitly bound widget action),
   - no two shown bindings collide on the same key within one
     `BINDINGS` block.
   These are cheap example-based tests rather than property tests
   — the binding tables don't take random input.

## What's deliberately manual

Three classes of TUI accessibility checks remain manual because
their fidelity needs an actual screen reader, an actual terminal
emulator, or a human in the loop:

- **Screen-reader narration of widgets.**  Whether VoiceOver / NVDA
  read each widget's role and content correctly depends on the
  terminal's accessibility bridge, Textual's emitted markup, and
  the user's screen-reader profile.  No automated test stands in
  for that combination today.
- **Braille display fidelity.**  Same reason — bridge-dependent.
- **Cognitive accessibility.**  Whether a screen "makes sense" to
  a first-time user with cognitive disability needs human review.
  We rely on the docs landing page (Phase 92.4) and the tutorial
  to keep this in check; there's no automated check.

When releasing a meaningful TUI change (new screen, restructured
keybindings, status-bar redesign), the manual recipe is:

1. Run `cantrip` in a macOS Terminal.app session with VoiceOver on
   (`Cmd-F5`).  Walk every screen with the keyboard and confirm
   the heading, the active widget, and the Footer hints are
   narrated.
2. Run `cantrip` in Windows Terminal with NVDA on.  Same walk.
3. Confirm that turning off the `inverted` colours / using a
   monochrome terminal still leaves all the status indicators
   (task chips, tool-block captions, status bar) legible — i.e.
   the *text* tells the whole story.

## Why this stays partly manual

Adding browser-style automated accessibility tooling to a TUI is
not a clear win:

- There is no Textual-side ARIA tree to assert against.  Textual
  emits SGR / OSC sequences that the terminal interprets; the
  *terminal* publishes the accessibility info, and each terminal
  emulator is different.
- A "snapshot diff" test catches visual regressions but doesn't
  tell us whether a screen reader can use the screen.
- The interesting failure modes (F-key capture, screen-reader
  treating Textual focus changes as flicker, contrast in a 16-colour
  terminal) all need the real stack to reproduce.

The position this note records: **automate the keyboard surface,
keep colour-as-redundant in every UI change, and run the manual
recipe before releases.**  Revisit if Textual ships a first-class
accessibility-tree export, or if we hear from a user that one of
the deferred items materially hurts their workflow.

## Cross-references

- [`WEB_UI_ACCESSIBILITY_AUDIT.md`](./WEB_UI_ACCESSIBILITY_AUDIT.md) — the
  full Web UI audit and its WCAG-aligned target.
- `tests/integration/web/test_accessibility.py` — the live-browser
  smoke that backs the web audit.
- `tests/unit/tui/test_accessibility_smoke.py` — the TUI keyboard-
  surface smoke that backs this note.
- `src/cantrip/tui/app.py` and `src/cantrip/tui/screens/*.py` — the
  `BINDINGS` lists the smoke walks.
