# Cantrip UI Design

## Overview

Cantrip provides two user interfaces — a **Textual TUI** (`cantrip run`) and a **Web UI**
(`cantrip --web`).  Both share a three-panel layout: task checklist, Juju status, and chat.
A shared event bus (`src/cantrip/ui/events.py`) ensures both interfaces receive identical
real-time updates from the agent layer.

### Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         Agent Layer                             │
│  CantripAgent · WorkQueue · Executor · Watcher · Preflight     │
│                         │                                       │
│                    EventBus.publish()                           │
│                         │                                       │
│              ┌──────────┴──────────┐                           │
│              ▼                     ▼                            │
│     ┌────────────────┐   ┌──────────────────┐                  │
│     │  Textual TUI   │   │    Web UI        │                  │
│     │  bus.subscribe  │   │  bus.subscribe   │                  │
│     │  → DOM updates  │   │  → WebSocket →   │                  │
│     │                │   │    browser JS     │                  │
│     └────────────────┘   └──────────────────┘                  │
└─────────────────────────────────────────────────────────────────┘
```

## Shared Event Contract

All UI updates flow through typed events defined in `src/cantrip/ui/events.py`.

| Event Type | Payload | Source |
|---|---|---|
| `TASK_UPDATED` | id, title, status, category, description, result, blocked_reason | WorkQueue mutation |
| `TASKS_SNAPSHOT` | full list of task dicts | Reconnect / state sync |
| `CHAT_MESSAGE` | role (user/assistant/system), content | Agent response, watcher |
| `THINKING_CHANGED` | active (bool) | Before/after agent processing |
| `JUJU_STATUS_CHANGED` | serialised status data | Watcher / status poll |
| `WATCHER_EVENT` | source, category, summary, detail, app, unit | EventWatcher |
| `STATUS_BAR_CHANGED` | task_label, cos_health, test_summary, watcher_status | Various |
| `PREFLIGHT_UPDATED` | group_index, item_index, status | PreflightRunner |
| `TOOL_INVOKED_PENDING` | tool_name, caption, tool_call_id, source | Pre-dispatch (Phase 82) |
| `TOOL_INVOKED` | tool_name, caption, success, duration_ms, source, tool_call_id, detail | Post-tool-call (`detail` = error+output text, failures only; drives the click-to-inspect modal) |

Adding a new UI feature means:
1. Add an `EventType` variant and factory function in `events.py`
2. Implement a handler in the TUI (`app.py`)
3. Handle the event type in the JS dispatcher (`cantrip.js`)

## Main Screen Layout

Both interfaces use the same logical layout:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  Header: Cantrip title, charm name, model info, shortcuts                  │
├────────────────────────────────────┬────────────────────────────────────────┤
│                                    │                                        │
│  Chat Panel                        │  Right Panels                          │
│  ─────────                         │  ────────────                          │
│                                    │  Tasks                                 │
│  User messages, agent responses,   │  ✓ Set up environment                 │
│  system notifications, thinking    │  ✓ Research workload                  │
│  indicator.                        │  ⟳ Build charm                        │
│                                    │  ○ Deploy                              │
│                                    │                                        │
│  [Input area]                      │  Juju Status                          │
│                                    │  ┌────────────┐                       │
│                                    │  │ redis-k8s  │                       │
│                                    │  │ ● active   │                       │
│                                    │  └────────────┘                       │
├────────────────────────────────────┴────────────────────────────────────────┤
│  Status bar: active task, COS health, test summary, watcher               │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Status Indicators

| Symbol | Meaning | Colour |
|--------|---------|--------|
| `✓` | Done | Green |
| `⟳` | Active | Blue |
| `○` | Pending | Grey |
| `◌` | Blocked | Yellow |
| `✗` | Failed | Red |
| `●` | App active | Green |

### Colour Roles (Phase 108.3)

`$primary` (Ubuntu orange `#E95420` under the bundled theme) is reserved for **brand
identity**, **modal focus surfaces**, and **section headings**.  Anything else moved to
quieter colours so the orange stops reading as wallpaper and starts reading as accent.

| Theme colour          | Role                                                  | Notable call sites                                                                                                  |
|-----------------------|-------------------------------------------------------|---------------------------------------------------------------------------------------------------------------------|
| `$primary`            | Brand identity, modal focus, section headings, user   | header brand mark, welcome wordmark, thinking indicator, modal `border: round`, help/trace section headings, user-message `border-left` |
| `$secondary`          | Assistant messages                                    | `MessageWidget.assistant` `border-left` only                                                                        |
| `$accent`             | In-flight / active / maintenance states               | tool-block left bar, tool-pending bar, progress-in-progress glyph, task-active row, task-divider, Juju maintenance |
| `$success`            | Successful completion                                 | task-done glyph, Juju app active                                                                                    |
| `$warning`            | User attention required (non-fatal)                   | shell-mode input border, shell-mode left bar, status-bar plan / paused / blocked tints                              |
| `$error`              | Failure                                               | tool-failed bar, shell-failed bar, task-failed glyph, status-bar yolo / budget-limited tints                        |
| `$panel-lighten-2`    | Suggestion-popup chrome                               | slash-command + `@`-mention popup `border-top` / `border-bottom`                                                    |
| `$surface-lighten-1`  | Inter-panel seams                                     | right-panel `border-left`, repo-stats `border-left`                                                                 |
| `$primary-background` | Header / status-bar / model-info-bar tint             | one-row tints under `Header`, `StatusBar`, `ModelInfoBar`                                                           |
| `$text-muted`         | Header timestamp chip, system messages, hidden hints  | timestamp `[HH:MM]` chip, system-role text, dim row labels                                                          |

The table is the source of truth for "where does that colour belong?".  A new widget that
reaches for `$primary` for plain chrome should pick a different colour from this list
instead — orange is for brand / focus / heading, not separators.

## Keyboard Shortcuts

### TUI

| Key | Action |
|-----|--------|
| `F1` | Help screen |
| `F2` | Toggle status panel |
| `F3` | Log viewer |
| `F4` | Trace/debug screen |
| `F5` | Toggle watcher |
| `F6` | Toggle file tree |
| `F7` | Toggle model info |
| `F8` | Integration graph |
| `F9` | Session transcript |
| `Ctrl+L` | Clear chat |
| `q` | Quit |

### Web UI

| Key | Action |
|-----|--------|
| `?` | Toggle help overlay |
| `L` | Toggle log viewer |
| `G` | Toggle integration graph |
| `R` | Refresh graph (when open) |
| `Esc` | Close overlay |
| `Enter` | Send message |

## Slash Commands

Slash commands are the shared cross-surface verb layer.  Every command routed by
`cantrip.agent.slash_commands.dispatch` is accepted verbatim by the CLI REPL,
the TUI chat input, and the Web chat panel.  Surface-native verbs (the CLI's
`/tasks` and `/status`, the TUI's `/feelings`) are each owned by one surface
and do not flow through the shared dispatcher.

| Verb | Purpose |
|------|---------|
| `/help`, `?` | Render the help block (shared verbs + args). |
| `/memory [scope]` | List memories; `/memory help` shows subcommands. |
| `/remember <kind> [scope] -- <title> -- <body>` | Write a memory. |
| `/forget <title>` | Delete a memory by title. |
| `/mcp` | List configured MCP servers; `/mcp help` for subcommands. |
| `/cost` | Token usage and estimated cost. |
| `/arena <prompt>` | Blind A/B compare two models; reply **A** / **B** / **tie** / **skip**. |
| `/export [html\|jsonl\|markdown] [path]` | Export the live transcript. |
| `/copy [last\|N]` | Copy a chat message to the system clipboard via OSC 52. |
| `/update` | Force a cache-bypassing PyPI check; prints the result. |
| `/update --no-check` | Persist `update_check_disabled = true` in `~/.config/cantrip/settings.json`. |
| `/update --check` | Clear the persistent opt-out. |
| `/quit`, `/exit` | Leave cantrip cleanly. |

`/update` is non-blocking — it returns a prelude (`"Checking PyPI for a newer
Cantrip…"`) immediately and then renders the verdict as a follow-up message
so a slow PyPI doesn't freeze the chat.  The running process still executes
the old code until restarted; the notice calls that out explicitly.
`CANTRIP_NO_UPDATE_CHECK=1` at the process level shadows the settings-file
toggle and stays in force for the session.

## Copy-Friendly Chat (Phase 76)

Inspired by Will McGugan's [Toad](https://github.com/batrachianai/toad)
agent, which exposes a Jupyter-style block cursor over the chat history
so users can navigate cells, copy them, or push them back into the
prompt.  Phase 76 investigated this pattern for Cantrip and shipped
the smallest concrete win: a `/copy` slash command that puts a chat
message on the system clipboard via OSC 52.  This section records what
was considered and what was deliberately deferred so a future phase
has a starting point if user demand surfaces.

### What shipped

* **`/copy [last|N]`** — copies a single message body, rendered as
  Markdown.  Default target is the most recent assistant message;
  `last` selects any role; `N` selects 1-based session index.  See
  `reference-cli.md` for full syntax.
* **OSC 52 emitter** in `cantrip.clipboard` — universal terminal
  clipboard escape that survives tmux, screen, and ssh when the
  terminal cooperates.  TUI uses Textual's `App.copy_to_clipboard`
  helper (Textual already understands the tmux passthrough wrap);
  CLI writes directly to `sys.__stdout__`.  Falls back to inline
  printing when the destination isn't a tty.
* **Web UI** inlines the payload in a fenced code block so browser
  select-and-copy works.  Server-pushed `navigator.clipboard.writeText`
  was rejected because the browser permissions policy requires a
  fresh user gesture; the SSE-delivered slash response doesn't
  qualify.

### What was deliberately deferred

* **Block-cursor navigation over the conversation** (Toad's headline
  feature).  Cantrip's `ChatWidget` is a flat `ScrollableContainer`
  of `Static` children, not a `ListView` of focusable per-block
  widgets.  Adopting block-cursor mode would require refactoring the
  chat widget to focusable per-message widgets, adding cursor state,
  rebuilding scroll-to-focus logic, and mirroring the same model in
  the Solid Web UI.  That's a medium-to-large change that should
  only happen if there's a concrete user-friction signal —
  "scrolling back and re-running a turn is painful" or "I want to
  cite an earlier message in a new prompt".  None has surfaced
  yet; revisit when (or if) one does.
* **Push back into the prompt composer** (Toad's reuse half).
  Without block-cursor navigation there's no obvious gesture; the
  closest existing affordance is `@@` proposed in Phase 67.1's
  session-tree work.  If that lands, a `/recall N` or similar
  variant on `/copy` becomes natural — log it then.
* **Hover/focus `[copy]` affordances on individual blocks** in
  either TUI or Web.  The TUI has no per-block focus model
  (ditto block-cursor); the Web UI has per-message DOM containers
  but no `data-message-id` attribute today.  Adding a per-block
  copy button is plausible Web-only future work; deferred until
  a user asks.
* **Markdown-vs-plain-text format picker.**  Toad ships one format
  (clipboard text); we ship one format (Markdown body).  Adding a
  picker would mostly add UI, not value.

### What would change the verdict

A future phase should reopen this work when one of:

* A user asks to "copy and edit an earlier turn" or "rewind to a
  prior message" — both pull in block-cursor navigation directly.
* The session-tree work in Phase 67.1 lands and the `@@` affordance
  proves popular — that's the cue to add `/copy` integration with
  the same picker so reuse-into-prompt and reuse-as-clipboard
  share one widget.
* Multiple users report that `/copy <N>` indices are too clumsy
  because the live chat doesn't display indices — solving that
  needs either visible per-block indices (cheap) or focusable
  blocks (block-cursor).

## Alternative Views

### Integration Graph

Available via F8 (TUI) or G (web).  Shows all deployed applications as status-coloured
cards with unit breakdowns, plus a relations section showing endpoint connections.

**TUI:** Rich-rendered panels in a modal screen with `[R] Refresh` and `[Esc] Close`.

**Web:** CSS card layout in a modal overlay.  App cards have coloured left borders matching
their status.  Relations listed below with provider → interface → requirer lines.

### Log Viewer

Available via F3 (TUI) or L (web).  Shows `juju debug-log` output.

**TUI:** Full modal screen with streaming log support and level filtering.

**Web:** Modal overlay fetching from `/api/logs`.

### Help

Available via F1 (TUI) or `?` (web).  Shows keyboard shortcuts and quick-start hints.

## Implementation Notes

### TUI (Textual)

- Entry point: `src/cantrip/tui/app.py` (`CantripApp`)
- Layout: CSS Grid via `cantrip.tcss`, two-column with left (chat) and right (tasks + status)
- Widgets: `ChatWidget`, `TaskChecklistWidget`, `MultiModelStatusWidget`, `StatusBar`
- Modal screens: `GraphScreen`, `LogScreen`, `HelpScreen`, `TraceScreen`, `TranscriptScreen`
- Event bus subscribers use `call_from_thread()` for thread-safe DOM updates
- Bundled themes via `tui/themes.py` with `--theme` CLI flag

### Web UI (aiohttp)

- Entry point: `src/cantrip/web/server.py`
- Template: `src/cantrip/web/templates/index.html.j2` (Jinja2)
- JavaScript: `src/cantrip/web/static/cantrip.js` (vanilla JS, IIFE pattern)
- CSS: `src/cantrip/web/static/style.css` (GitHub Dark theme, CSS Grid)
- Real-time: WebSocket at `/ws`; wildcard bus subscriber forwards all events as JSON
- REST endpoints: `/api/state`, `/api/juju-status`, `/api/logs`
- Overlays: help, logs, graph — toggled via `.hidden` class

### Responsive Behaviour (Web)

At `< 700px` the two-column layout collapses to a single column with the right panels
stacked below the chat.

### Activity Flavour Labels

Where older copy said `⟳ Thinking...`, both surfaces now render a randomly-picked
spellcasting-themed label: `⟳ Conjuring...`, `⟳ Scrying...`, `⟳ Thumbing the
grimoire...`, and so on.  The label is flavour only — the agent is literally
thinking; the verb is just theme-matching to the `cantrip`/`juju` naming.

- **Pool:** `src/cantrip/ui/flavour.py` holds the canonical list
  (`flavour.think_pool()`).  `src/cantrip/web/static/cantrip.js` carries a
  JavaScript mirror so the browser can pick client-side when the server
  broadcasts a `thinking` event.  `tests/unit/test_ui_flavour.py` diffs the two
  so drift fails the build.
- **Cadence:** **stable per thinking phase, re-rolled on every transition back
  to thinking.**  A turn that runs a tool, returns to thinking, runs more tools,
  returns to thinking again gets two different labels across its two thinking
  phases.  The TUI and Web honour this by calling `pick_activity_label()` /
  `pickFlavourLabel()` at each phase entry rather than caching a label per turn.
- **What stays literal:** `⟳ Streaming...` (describes output delivery, not
  thought) and `⟳ running: <tool>` (describes an actual tool call) both stay
  as-is.  Flavour text replaces only the generic "LLM is cogitating" label.
- **Category hints:** `ActivityCategory.THINK` is the default.  `RESEARCH` and
  `BUILD` narrow the pool for themed work (divination verbs for research,
  forging verbs for build).  The call-site surface defaults to THINK; narrower
  categories are available when a surface knows what the agent is doing.

### Adding a New View

1. **Event bus:** If the view needs new data, add an `EventType` and factory in `events.py`.
2. **TUI:** Create a new `ModalScreen` in `src/cantrip/tui/screens/`, add an `F-key` binding
   in `CantripApp`, subscribe to bus events if needed.
3. **Web:** Add an overlay `<div>` in `index.html.j2`, a toggle function in `cantrip.js`,
   CSS in `style.css`, and a keyboard shortcut in `_handleKeyDown`.
4. **Tests:** Add assertions in `test_web_server.py` (JS/CSS/template presence) and
   `test_ui_events.py` (event contract).
