# Cantrip TUI Design

## Overview

Textual-based TUI with three-panel layout. The **task checklist** is the primary way the
user understands what the agent is doing. The **Juju status** panel shows the current state
of the deployment. The **chat** panel is for conversation — mostly the agent presenting
findings and the user confirming or steering.

## Main Screen

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  Cantrip v0.1.0                                [dev:k8s] [cos:k8s] [F1 Help]│
├──────────────────────┬──────────────────┬───────────────────────────────────┤
│                      │                  │                                   │
│  Tasks               │  Juju Status     │  Chat                             │
│  ─────               │  ───────────     │  ────                             │
│                      │                  │                                   │
│  ✓ Set up environ.   │  Model: dev (k8s)│  > build a charm for redis       │
│  ✓ Clone + analyse   │  Apps: 1         │                                   │
│  ✓ Research Redis    │                  │  Researching Redis operational    │
│    operations        │  ┌────────────┐  │  patterns...                      │
│  ✓ Survey Charmhub   │  │ redis-k8s  │  │                                   │
│  ✓ Design proposal   │  │ ⟳ waiting  │  │  I've researched how Redis is     │
│  ✓ Scaffold charm    │  │ 1 unit     │  │  typically operated. Here's my    │
│  ⟳ Deploy to dev     │  └─────┬──────┘  │  proposed design:                 │
│  ○ Add observability │        │ cos     │                                   │
│  ○ Run unit tests    │        ▼         │  • K8s charm (official OCI image) │
│  ○ Add integrations  │  ┌────────────┐  │  • Primary/replica with Sentinel  │
│  ○ Integration tests │  │ COS (6)    │  │  • AOF persistence by default     │
│  ○ Validate          │  │ ● healthy  │  │  • Backup action via redis-cli    │
│                      │  └────────────┘  │  • COS + ingress integrations     │
│                      │                  │                                   │
│                      │                  │  Shall I proceed with this, or     │
│                      │                  │  would you like to adjust?         │
│                      │                  │                                   │
│                      │                  │  [Type your message...]            │
│                      │                  │                                   │
├──────────────────────┴──────────────────┴───────────────────────────────────┤
│  [⟳ Deploying redis-k8s] [● COS healthy] [👁 Watching]                      │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Layout Breakdown

### Header Bar
```
│  Cantrip v0.1.0                                [dev:k8s] [cos:k8s] [F1 Help]│
```
- Product name and version
- Active models with substrate type
- Help shortcut

### Left Panel: Task Checklist

The primary panel. Shows every task in the work queue with live status updates.

```
  Tasks
  ─────

  ✓ Set up environ.
  ✓ Clone + analyse
  ✓ Research Redis operations
  ✓ Survey Charmhub
  ✓ Design proposal
  ✓ Scaffold charm
  ⟳ Deploy to dev
  ○ Add observability
  ○ Run unit tests
  ○ Add integrations
  ○ Integration tests
  ○ Validate
```

**Status indicators:**
- `✓` done (green)
- `⟳` active (blue, with optional elapsed time)
- `○` pending (grey)
- `◌` blocked — waiting for user input or a dependency (yellow)
- `✗` failed (red)

Selecting a task shows its result summary and any errors. Tasks added by the
watcher (e.g. "diagnose hook failure") appear dynamically.

### Centre Panel: Juju Status

Shows the current state of the deployment — app boxes, status indicators,
relation lines. Smaller than in the old two-panel layout because the task
checklist now carries the primary information load.

**Dev Model (expanded):**
```
  Model: dev (k8s)
  Apps: 1

  ┌────────────┐
  │ redis-k8s  │
  │ ● active   │
  │ 1 unit     │
  └─────┬──────┘
        │ cos
        ▼
  ┌────────────┐
  │ COS (6)    │
  │ ● healthy  │
  └────────────┘
```

**Status indicators:**
- `●` active (green)
- `○` waiting (yellow)
- `◌` blocked (red)
- `◐` maintenance (blue)

### Right Panel: Chat

Conversation between user and agent. The chat is where:
- The agent presents design proposals for confirmation
- The user steers priorities or provides domain expertise
- The agent notifies about watcher events that need user input

Standard chat interface:
- Scrollable message history
- User messages prefixed with `>`
- Agent messages left-aligned
- Inline progress indicators (`✓` `⟳` `✗`) for preflight steps

### Input Area
```
  [Type your message...]
```

- Single line, expands if needed
- Enter to send
- Up arrow for history

### Status Bar
```
│  [⟳ Deploying redis-k8s] [● COS healthy] [👁 Watching]                      │
```

- Current active task (from work queue)
- COS health summary
- Test results (when available)
- Watcher status
- Compact, doesn't demand attention

## Keyboard Shortcuts

| Key | Action |
|-----|--------|
| `F1` | Help screen |
| `F2` | Toggle status panel width |
| `F3` | Logs view |
| `F4` | Debug mode |
| `Ctrl+L` | Clear chat |
| `Ctrl+C` | Cancel current operation |
| `Tab` | Switch focus (status ↔ chat) |
| `q` | Quit (with confirmation if tasks running) |

## Alternative Views

### Logs View (F3)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  Logs: flask-app/0                                    [F3 Back] [F4 Filter] │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  14:23:01 unit-flask-app-0 INFO Starting Flask application                  │
│  14:23:02 unit-flask-app-0 INFO Listening on 0.0.0.0:8000                   │
│  14:23:05 unit-flask-app-0 DEBUG Health check passed                        │
│  14:23:10 unit-flask-app-0 INFO Request: GET /                              │
│  14:23:10 unit-flask-app-0 INFO Response: 200 OK (15ms)                     │
│                                                                             │
│  ──────────────────────────────────────────────────────────────────────────│
│  Filter: [all levels ▼] [flask-app/0 ▼]              [Auto-scroll: ON]     │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Model Graph View (expanded)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  Model Graph: dev                                              [F2 Compact] │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│                        ┌───────────────┐                                    │
│                        │   traefik     │                                    │
│                        │   ● active    │                                    │
│                        └───────┬───────┘                                    │
│                                │ ingress                                    │
│                                ▼                                            │
│                        ┌───────────────┐                                    │
│                        │  flask-app    │                                    │
│                        │  ● active     │                                    │
│                        └───┬───────┬───┘                                    │
│               postgresql   │       │   tracing                              │
│                ┌───────────┘       └───────────┐                            │
│                ▼                               ▼                            │
│        ┌───────────────┐               ┌─────────────┐                      │
│        │  postgresql   │               │    tempo    │ (cos model)          │
│        │  ● active     │               │  ● active   │                      │
│        └───────────────┘               └─────────────┘                      │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Help Screen (F1)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  Cantrip Help                                                   [Esc Close] │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  Quick Start                                                                │
│  ───────────                                                                │
│  Just describe what you want to charm:                                      │
│    > build a charm for my flask app                                         │
│    > add postgresql integration                                             │
│    > add a backup action                                                    │
│                                                                             │
│  Keyboard Shortcuts                                                         │
│  ──────────────────                                                         │
│  F1        This help                                                        │
│  F2        Toggle status panel                                              │
│  F3        View logs                                                        │
│  F4        Debug mode                                                       │
│  Ctrl+L    Clear chat                                                       │
│  Ctrl+C    Cancel operation                                                 │
│  q         Quit                                                             │
│                                                                             │
│  Links                                                                      │
│  ─────                                                                      │
│  Grafana:  http://localhost:3000                                            │
│  Docs:     https://juju.is/docs                                             │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Responsive Behaviour

### Medium Terminal (< 120 cols)

Drop Juju status panel; tasks + chat side by side:
```
┌──────────────────────────────────────────┐
│  Cantrip v0.1.0        [dev:k8s] [F1]    │
├───────────────┬──────────────────────────┤
│  Tasks        │  Chat                    │
│  ─────        │  ────                    │
│  ✓ Setup env  │  > build a charm for     │
│  ✓ Research   │    redis                 │
│  ⟳ Deploy     │                          │
│  ○ Tests      │  Deploying redis-k8s...  │
│               │                          │
│               │  [Type here...]          │
├───────────────┴──────────────────────────┤
│  [⟳ Deploying] [● COS] [👁 Watching]     │
└──────────────────────────────────────────┘
```

### Narrow Terminal (< 80 cols)

Stack tasks (collapsed) above chat:
```
┌─────────────────────────┐
│  Cantrip      [dev:k8s] │
├─────────────────────────┤
│  ✓✓✓⟳○○○○  7/12 tasks   │
├─────────────────────────┤
│  Chat                   │
│  > build a charm...     │
│  Deploying redis-k8s... │
│                         │
│  [Type here...]         │
├─────────────────────────┤
│  [⟳ Deploying]          │
└─────────────────────────┘
```

### Very Narrow (< 60 cols)

Chat only, task progress in status bar:
```
┌───────────────────────┐
│ Cantrip  7/12 tasks   │
├───────────────────────┤
│ > build a charm       │
│                       │
│ Deploying...          │
│                       │
│ [Type here...]        │
└───────────────────────┘
```

## Colour Scheme

Using standard terminal colours for compatibility:

| Element | Colour |
|---------|--------|
| Active status | Green |
| Waiting status | Yellow |
| Blocked/error | Red |
| Maintenance | Blue |
| User input | White/default |
| Agent response | Cyan |
| Progress indicator | Blue |
| Success | Green |
| Failure | Red |
| Muted/secondary | Grey |

## Textual Components

```python
# Main app structure
class CantripApp(App):
    CSS_PATH = "cantrip.tcss"
    BINDINGS = [
        ("f1", "help", "Help"),
        ("f2", "toggle_status", "Toggle Status"),
        ("f3", "logs", "Logs"),
        ("f4", "debug", "Debug"),
        ("f5", "toggle_watcher", "Toggle Watcher"),
        ("q", "quit", "Quit"),
    ]

# Key widgets
class TaskListWidget(Widget):
    """Live task checklist driven by WorkQueue state."""

class JujuStatusWidget(Widget):
    """Displays juju status with app boxes and relations."""

class ChatWidget(Widget):
    """Chat history and input."""

class StatusBar(Widget):
    """Bottom bar with active task, COS health, test summary, watcher status."""

# Future
class ModelGraphWidget(Widget):
    """Visual representation of model topology (Phase 6)."""
```
