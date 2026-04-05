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

### Adding a New View

1. **Event bus:** If the view needs new data, add an `EventType` and factory in `events.py`.
2. **TUI:** Create a new `ModalScreen` in `src/cantrip/tui/screens/`, add an `F-key` binding
   in `CantripApp`, subscribe to bus events if needed.
3. **Web:** Add an overlay `<div>` in `index.html.j2`, a toggle function in `cantrip.js`,
   CSS in `style.css`, and a keyboard shortcut in `_handleKeyDown`.
4. **Tests:** Add assertions in `test_web_server.py` (JS/CSS/template presence) and
   `test_ui_events.py` (event contract).
