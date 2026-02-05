# Cantrip TUI Design

## Overview

Textual-based TUI with split layout. Primary focus is the conversation; status display supports awareness without requiring user attention.

## Main Screen

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  Cantrip v0.1.0                              [dev:lxd] [cos:k8s]  [F1 Help] │
├───────────────────────────────────┬─────────────────────────────────────────┤
│                                   │                                         │
│  Juju Status                      │  Chat                                   │
│  ───────────                      │  ────                                   │
│                                   │                                         │
│  Model: dev (lxd)                 │  ┌─────────────────────────────────────┐│
│  Apps: 2  Units: 3                │  │ > build a charm for my flask app   ││
│                                   │  │                                     ││
│  ┌─────────────┐                  │  │ I'll create a 12-factor charm for  ││
│  │ flask-app   │ ← you are here   │  │ your Flask application.            ││
│  │ ● active    │                  │  │                                     ││
│  │ 1 unit      │                  │  │ Detecting framework... Flask 2.3   ││
│  └──────┬──────┘                  │  │ ✓ Generated rockcraft.yaml         ││
│         │ postgresql              │  │ ✓ Building rock...                 ││
│         ▼                         │  │ ⟳ Deploying to dev model           ││
│  ┌─────────────┐                  │  │                                     ││
│  │ postgresql  │                  │  │                                     ││
│  │ ● active    │                  │  │                                     ││
│  │ 1 unit      │                  │  │                                     ││
│  └─────────────┘                  │  │                                     ││
│                                   │  │                                     ││
│  ─────────────────                │  └─────────────────────────────────────┘│
│  Model: cos (k8s)                 │                                         │
│  Apps: 6  ● healthy               │  ┌─────────────────────────────────────┐│
│                                   │  │ Type your message...               ││
│                                   │  └─────────────────────────────────────┘│
│                                   │                                         │
├───────────────────────────────────┴─────────────────────────────────────────┤
│  [⟳ Building rock] [● COS healthy] [Tests: 3/5 passing]                     │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Layout Breakdown

### Header Bar
```
│  Cantrip v0.1.0                              [dev:lxd] [cos:k8s]  [F1 Help] │
```
- Product name and version
- Active models with substrate type
- Help shortcut

### Left Panel: Juju Status

Two sections - dev model (main) and cos model (collapsed summary).

**Dev Model (expanded):**
```
  Model: dev (lxd)
  Apps: 2  Units: 3

  ┌─────────────┐
  │ flask-app   │ ← you are here
  │ ● active    │
  │ 1 unit      │
  └──────┬──────┘
         │ postgresql
         ▼
  ┌─────────────┐
  │ postgresql  │
  │ ● active    │
  │ 1 unit      │
  └─────────────┘
```

**Status indicators:**
- `●` active (green)
- `○` waiting (yellow)
- `◌` blocked (red)
- `◐` maintenance (blue)

**Integration lines:**
- `│` vertical connection
- `─` horizontal connection
- Labelled with relation name

**COS Model (collapsed):**
```
  Model: cos (k8s)
  Apps: 6  ● healthy
```

Expandable with click/key to show full COS status.

### Right Panel: Chat

Standard chat interface:
- Scrollable message history
- User messages right-aligned or prefixed with `>`
- Agent messages left-aligned
- Progress indicators inline:
  - `✓` completed step
  - `⟳` in progress
  - `✗` failed

### Input Area
```
  ┌─────────────────────────────────────┐
  │ Type your message...               │
  └─────────────────────────────────────┘
```

- Single line, expands if needed
- Enter to send
- Up arrow for history
- Tab completion for common commands

### Status Bar
```
│  [⟳ Building rock] [● COS healthy] [Tests: 3/5 passing]                     │
```

- Background task indicators
- COS health summary
- Test status (if running)
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

### Narrow Terminal (< 100 cols)

Stack panels vertically:
```
┌─────────────────────────┐
│  Cantrip      [dev:lxd] │
├─────────────────────────┤
│  Status (collapsed)     │
│  flask-app ● active     │
│  postgresql ● active    │
├─────────────────────────┤
│  Chat                   │
│  > build a charm...     │
│  Creating charm...      │
│  ✓ Done                 │
│                         │
│  [Type here...]         │
├─────────────────────────┤
│  [⟳ Building]           │
└─────────────────────────┘
```

### Very Narrow (< 60 cols)

Chat only, status in bar:
```
┌───────────────────────┐
│ Cantrip  2 apps ● ok  │
├───────────────────────┤
│ > build a charm       │
│                       │
│ Creating...           │
│ ✓ Done                │
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
        ("f2", "toggle_status", "Status"),
        ("f3", "logs", "Logs"),
        ("f4", "debug", "Debug"),
        ("q", "quit", "Quit"),
    ]

# Key widgets
class JujuStatusWidget(Widget):
    """Displays juju status with app boxes and relations."""

class ChatWidget(Widget):
    """Chat history and input."""

class ModelGraphWidget(Widget):
    """Visual representation of model topology."""

class StatusBar(Widget):
    """Bottom bar with background task status."""
```
