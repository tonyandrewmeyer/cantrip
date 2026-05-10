---
title: "TUI screens and shortcuts — Cantrip"
description: "The function-key screens and status panes that make up the Cantrip terminal UI."
h1: "TUI screens and shortcuts"
subtitle: "The Cantrip TUI layers modal screens on top of the chat panel so you can inspect Juju state, tail logs, and open files without breaking the session. This page catalogues them."
section: explanation
breadcrumb_label: "TUI screens and shortcuts"
on_this_page:
  - { anchor: "overview", label: "Overview" }
  - { anchor: "function-keys", label: "Function-key screens" }
  - { anchor: "file-pane", label: "Charm file pane" }
  - { anchor: "file-detail", label: "File detail" }
  - { anchor: "logs", label: "Logs" }
  - { anchor: "graph", label: "Integration graph" }
  - { anchor: "traces", label: "Traces and COS endpoints" }
  - { anchor: "status-panes", label: "Dev and COS status panes" }
  - { anchor: "confirmations", label: "Confirmation prompts" }
  - { anchor: "shell-mode", label: "Shell mode" }
---

{#overview}
## Overview

The main TUI view is a chat panel for talking to the agent, flanked
by status panes and a file tree. Function keys open modal screens
over the chat; <kbd>Esc</kbd> always closes the current modal.
Every modal shares a common chrome: a title bar, a scrollable body,
and a footer listing its screen-specific shortcuts.

{#function-keys}
## Function-key screens

| Key | Screen | What it shows |
|---|---|---|
| <kbd>F1</kbd> | Help | Keyboard shortcuts and slash-command reference. |
| <kbd>F2</kbd> | Status toggle | Show or hide the Dev / COS status panes on the right. |
| <kbd>F3</kbd> | Logs | Tail `juju debug-log` for the dev model — see [Logs](#logs) for filters. |
| <kbd>F4</kbd> | Debug / Traces | COS endpoint URLs with Grafana deep-links — see [Traces and COS endpoints](#traces). |
| <kbd>F5</kbd> | Watcher toggle | Toggle the always-on Juju event watcher; when on, the task pane surfaces recent hook and unit events inline. |
| <kbd>F6</kbd> | Files toggle | Show or hide the charm file pane (tree plus repo-stats sidebar — see [Charm file pane](#file-pane)). Click a file to open the [File detail](#file-detail) modal. |
| <kbd>F7</kbd> | Model info | Current primary and light model, cost, and token usage. |
| <kbd>F8</kbd> | Integration graph | Deployed apps and their relations — see [Integration graph](#graph). |
| <kbd>F9</kbd> | Transcript | Browse the persisted conversation history. |

{#file-pane}
## Charm file pane

The right side of the TUI carries a **Charm files** pane, toggled
with <kbd>F6</kbd>. Two surfaces sit side by side:

- A live directory tree rooted at the charm working directory,
  filtered to hide noise like `.git`, `__pycache__`, `.venv`,
  `node_modules`, `.tox`, and `.cantrip`. The tree refreshes on a
  3-second tick so files the agent writes appear without manual
  reload. Selecting a file opens the [File detail](#file-detail)
  modal.
- A right-docked **repo-stats sidebar** with four glance-and-go
  signals:
  - **Recent** — the working-tree-newest file with a relative
    timestamp, so you notice when the agent has touched something
    during a long-running task.
  - **Commit** — short hash, subject, and age of the working
    tree's HEAD commit. Reads as `—` for non-git directories or
    repositories with no commits.
  - **Lines** — total source lines with a top-two language
    breakdown (`py`, `yaml`, `toml`, `md`, `j2`, `rs`, `go`, …).
    Files larger than 1 MB and unknown extensions do not
    contribute to the count.
  - **Files** — total file and directory counts inside the same
    filtered walk used by the tree. A `(truncated)` tag appears
    if the walk hits the defensive 5 000-file cap, which only
    fires for an accidentally-broad working directory.

The sidebar is hidden automatically when the pane is too narrow to
host both columns; widen the terminal (or close the side panels
with <kbd>F2</kbd>) to bring it back. Test-pass and lint state are
deliberately not in the slate today — they need a bus event from
the runner to avoid showing stale data and will land alongside that
work.

{#file-detail}
## File detail

Clicking a file in the <kbd>F6</kbd> file pane opens the
**File detail** modal. It shows the path, size,
modification time, a best-effort summary of the file’s
purpose derived from its contents, the five most recent
`git log` entries that touched the file, and a syntax-
highlighted preview rendered via Rich’s `Syntax`.

Shortcut: <kbd>R</kbd> refreshes the modal against the current
working tree so you can re-open after a subagent writes to the
file. <kbd>Esc</kbd> closes.

{#tool-failure}
## Tool failure detail

When a tool call fails, the chat shows a one-line `✗` block with a
brief caption and a dim `(details)` hint. Clicking that block opens
the **Tool failure** modal, which shows the captured error summary
and the tool’s full output — stderr, test logs, tracebacks — so you
can see what actually went wrong without opening the transcript
viewer. <kbd>Esc</kbd> closes. (The block is only clickable when the
agent captured detail for that failure; successful calls are never
clickable.)

{#logs}
## Logs

The <kbd>F3</kbd> **Logs** screen tails
`juju debug-log` for the dev model. Three shortcuts
re-scope the view without leaving the modal:

- <kbd>L</kbd> cycles the level filter through
  `WARNING`, `INFO`, `DEBUG`,
  `ERROR`.
- <kbd>M</kbd> cycles through the deployed apps and their units so
  you can focus on one workload at a time.
- <kbd>T</kbd> toggles streaming: off fetches the last 200 lines
  once; on subscribes to live updates.

{#graph}
## Integration graph

The <kbd>F8</kbd> **Integration graph** shows deployed
apps and their relations. <kbd>F</kbd> cycles a status filter
through four states: all apps, only `blocked`, only
`waiting`, or both — useful for zeroing in on
apps that need attention when the model has a lot going on.
<kbd>R</kbd> refreshes against the live status.

{#traces}
## Traces and COS endpoints

The <kbd>F4</kbd> **Debug** screen lists the URLs the
agent uses to inspect the COS stack — Prometheus, Loki, Tempo,
and Grafana — and builds Grafana deep-links pre-populated with
the dev model and time range so one click opens the right dashboard.
Each endpoint shows a reachability indicator derived from a live
probe so an unreachable endpoint isn’t hidden behind a broken
link.

{#status-panes}
## Dev and COS status panes

The right-hand side of the TUI shows two always-on panes, toggled
together with <kbd>F2</kbd>:

- **Dev model** — controller, model name, and a
  short summary of each deployed app’s status.
- **COS model** — labelled summary (units,
  relations, offers) of the COS model backing observability, plus
  an explicit list of cross-model offers so you can see at a glance
  which apps are consuming the stack.

Both panes refresh from the event watcher, so they stay current
without polling. Expanding either pane scrolls rather than
clipping when the app or offer list grows past the pane height.

{#confirmations}
## Confirmation prompts

Work that affects the outside world — pushing a branch,
creating a GitHub repo, working on a triaged issue, spending a
Best-of-N racing budget — is never done silently. Instead,
Cantrip emits a **CONFIRM task** that appears in the
task panel as a blocked row and prints a framed
“… confirmation” prompt in the chat log. The
task stays blocked until the user replies `approve` or
`skip`, so the prompt never disappears off-screen.

The most common confirmation is the **repo bootstrap**
offer, which fires when Cantrip finishes a build inside a directory
that has no GitHub remote and `gh` is available. The
default repository name follows the Canonical upstream convention
— if the charm is `foo`, the suggested name is
`foo-operator`. Names that already end in
`-operator`, `-charm`, `-k8s`, or
`-machine` are kept as-is.

Reply tokens for the bootstrap prompt:

- `approve` (or `yes`) — create the
  repo with the suggested name, privately by default.
- `skip` (or `no`) — dismiss the
  offer; Cantrip does not re-ask for the rest of the session.
- `public` anywhere in the reply flips the repo to
  public visibility.
- `name=my-repo` overrides the suggested name.
- `org=canonical` creates the repo under that
  organisation instead of your personal account.
- `desc=My charm` sets the repository description.

Tokens can be combined: `approve public org=canonical
name=my-charm-operator desc=Runs my charm`.

{#shell-mode}
## Shell mode

<kbd>Ctrl+X</kbd> on the chat input toggles **shell mode**. The
input border tints with the warning colour and the placeholder
changes to `$ shell command (Ctrl-X to leave shell mode)` so the
state is visible at a glance. Pressing <kbd>Enter</kbd> in shell
mode runs the command as a subprocess and prints the output as a
`$ cmd` block in the chat — the agent never sees it, no tokens are
spent, and `Ctrl+X` again returns to the normal agent input.

Shell mode is a convenience pass-through to `subprocess`, not a
full shell. Commands are tokenised with `shlex` and executed under
the same Phase 49 sandbox the agent's `run_command` tool uses, so
shell features that the underlying `subprocess` call cannot handle
on its own are not supported:

- No `cd` — there is no shell process to keep state.
- No shell aliases or shell variables.
- No pipelines (`|`), redirection (`>`/`<`), command substitution
  (`` `…` ``, `$(…)`), or compound commands (`&&`, `;`) — the
  command is `argv`, not a shell line.
- Network access is disabled by the sandbox unless the running
  Cantrip session was launched with a network-enabled policy.

For interactive shell needs, drop to a real terminal in another
window.

Prefix the command with `$$` for **incognito** shell mode. The
input still runs as a subprocess and the output still renders into
the chat for the user to read, but the persisted row is marked
`hidden_from_agent: true` so any future context-assembly path that
would otherwise include shell history skips it. Useful for
commands whose output you want visible to *you* but never to the
LLM:

- `$$ juju show-unit mycharm/0 --format json` — relation databags
  often contain credentials.
- `$$ kubectl get secret -o yaml` — Kubernetes secrets.
- `$$ cat .env` — local development credentials.
