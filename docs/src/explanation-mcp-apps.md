---
title: "MCP Apps in the chat — Cantrip"
description: "How Cantrip renders MCP server HTML responses as sandboxed iframes in the Web UI and bridges postMessage tool calls through the permission gate."
h1: "MCP Apps in the chat"
subtitle: "Some configuration is easier as a form than as a JSON blob. Cantrip's Web UI renders MCP-server-returned HTML inline and routes the app's tool calls through the same permission and audit machinery as any agent-initiated call."
section: explanation
breadcrumb_label: "MCP Apps"
on_this_page:
  - { anchor: "what", label: "What is an MCP App" }
  - { anchor: "render", label: "How the iframe is rendered" }
  - { anchor: "bridge", label: "The postMessage bridge" }
  - { anchor: "permissions", label: "Permissions and audit" }
  - { anchor: "tui", label: "TUI fallback" }
  - { anchor: "example", label: "Worked example: a pebble-layer editor" }
---

{#what}
## What is an MCP App

The Model Context Protocol's [MCP Apps extension][spec] lets a server
return interactive HTML alongside its textual reply. The standard is
supported by Claude Desktop, VS Code Copilot, Goose, Postman, and
MCPJam — and now by Cantrip's Web UI.

Concretely: when an MCP tool result includes a content block tagged
`type: "ui"` with `mime: text/html`, conformant hosts render that HTML
in a sandboxed iframe inline in the chat. A small `postMessage` protocol
lets the iframe ask the host to run tool calls and receive structured
results.

For Cantrip this turns awkward configuration JSON — pebble layers,
relation databags, COS dashboards, bundle topologies — into forms a
user can drive directly, instead of pasting YAML into a chat box.

[spec]: https://modelcontextprotocol.io/extensions/apps/overview

{#render}
## How the iframe is rendered

When `MCPClient.call_tool()` returns a result containing one or more
`ui` blocks, Cantrip's MCP controller mints an `app_id` for each one
and publishes an `mcp_app_render` event on the shared event bus. The
Web UI's dispatcher catches the event, creates a chat-block container,
and attaches a sandboxed `<iframe>`:

```html
<iframe sandbox="allow-scripts allow-forms" srcdoc="...server html..."></iframe>
```

The sandbox attributes are mandatory and intentionally narrow:

- **`allow-scripts`** — the app's own JavaScript can run.
- **`allow-forms`** — the app can submit forms (handled in-iframe, not
  by the host).
- **No `allow-same-origin`** — the iframe is treated as a *different*
  origin from the parent. It cannot read the parent's cookies, its
  `localStorage`, or any DOM node outside itself. All communication
  with the host happens via `postMessage`.

The iframe's height defaults to 400&nbsp;px (cantrip clamps to a 800&nbsp;px
ceiling regardless of what the server suggests via `max_height_px`) so
a malicious or buggy app cannot blow out the chat layout.

{#bridge}
## The postMessage bridge

Inside the iframe, the app's JavaScript can send a structured tool
call to the host:

```js
window.parent.postMessage(
  {
    type: 'tool_call',
    requestId: 'r1',
    name: 'read_file',
    arguments: { path: 'README.md' },
  },
  '*',
);
```

Cantrip's Web UI listens for messages on `window`, validates that the
sender is one of the iframes it knows about (matched by
`event.source === iframe.contentWindow`), and forwards the call over
the WebSocket as an `mcp_app_tool_call` message:

```json
{
  "type": "mcp_app_tool_call",
  "data": { "app_id": "...", "request_id": "r1", "name": "read_file", "arguments": { "path": "README.md" } }
}
```

The backend routes the call through `MCPController.handle_app_tool_call`,
which runs it through Cantrip's permission gate and tool registry (see
below), then publishes an `mcp_app_tool_result` event. The Web UI
catches the result event and posts it back into the iframe:

```js
iframe.contentWindow.postMessage(
  { type: 'tool_result', requestId: 'r1', success: true, output: '...' },
  '*',
);
```

The app's own listener resolves the pending request and updates its UI.

{#permissions}
## Permissions and audit

An iframe-emitted tool call is **not** trusted ambiently. It goes
through exactly the same `evaluate_permissions()` gate as any
agent-initiated call, with one extra signal: the per-agent overlay
name is `"mcp-app"`, so users can write rules that scope only to
iframe-emitted calls:

```yaml
# .cantrip/permissions.yaml
tools:
  edit_file: deny     # the agent itself can edit
  read_file: allow
agents:
  mcp-app:
    tools:
      "*": ask        # but any iframe call asks first
      read_file: allow
```

- **ALLOW** dispatches via the agent's shared tool registry; the
  iframe sees the tool's output.
- **DENY** rejects without dispatching; the iframe sees an error
  result with the matched rule's reason.
- **ASK** parks on the same `PermissionManager` the rest of the
  agent uses — a CONFIRM task appears in the TUI / Web UI; once the
  user approves, the call proceeds and the iframe sees the result.

Every decision (ALLOWED / DENIED / REVIEW_REQUESTED) writes one row
to `.cantrip-audit.jsonl` with `policy_name="mcp-app:<server>"` so an
operator can `grep` the audit trail for exactly what an MCP App did
during the session. The same call also fires `tool_invoked_pending`
and `tool_invoked` events tagged `source="mcp-app"` so the transcript
exporter records the call alongside agent-initiated ones.

{#tui}
## TUI fallback

The TUI has no iframe. When an `mcp_app_render` event arrives it
renders a one-line marker in chat:

```text
[MCP App: Pebble Editor; open in web UI at http://localhost:8471]
```

…followed by any text-form fallback the server attached. Users who
want to drive the form can switch to the Web UI; the app stays in the
chat history of the same session because both UIs subscribe to the
same event bus.

{#example}
## Worked example: a pebble-layer editor

The MCP Apps spec is most useful for shapes that are awkward to edit
as JSON. A reference example (not shipped in tree) is a
**pebble-layer editor** MCP server with one tool:

```
edit_pebble_layer(charm: str, container: str, existing_yaml: str) -> result
```

When called, the server returns:

1. A text reply ("Here is the current layer; edit it below"), and
2. A `ui` block with HTML for a form: a `<textarea>` pre-filled with
   `existing_yaml`, a "Validate" button (calls a YAML-parsing tool in
   the iframe), and a "Save" button.

The Save button's handler builds the tool call:

```js
function save() {
  window.parent.postMessage({
    type: 'tool_call',
    requestId: crypto.randomUUID(),
    name: 'mcp__pebble__commit_layer',
    arguments: {
      charm: charm,
      container: container,
      yaml: document.querySelector('#layer').value,
    },
  }, '*');
}
```

If the operator's `permissions.yaml` says `mcp__pebble__commit_layer:
ask` for `agents.mcp-app`, Cantrip parks the request on the CONFIRM
surface; the operator approves it; the iframe sees `{success: true,
output: "Committed."}` and shows a green checkmark. The whole exchange
is recorded in `.cantrip-audit.jsonl` and the transcript export.

See also:

- [How Cantrip works](explanation-architecture.html)
- [Configure tool permissions](howto-permissions.html)
- [Configure MCP servers](howto-mcp.html)
