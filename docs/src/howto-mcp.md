---
title: "How to configure MCP servers — Cantrip"
description: "Attach third-party MCP servers to Cantrip: cantrip.mcp.yaml, stdio and HTTP transports, OAuth, and marketplaces."
h1: "Configure MCP servers"
subtitle: "Attach third-party tools to Cantrip via the Model Context Protocol."
section: howto
breadcrumb_label: "Configure MCP servers"
see_also:
  - label: "Slash commands reference"
    href: "reference-cli.html#slash-commands"
  - label: "Authoring MCP servers"
    href: "https://github.com/tonyandrewmeyer/cantrip/blob/main/design/MCP_SERVERS.md"
    external: true
---

{#what}
## What MCP gives you

MCP is the cross-vendor standard (Claude Code, Cursor, Codex,
Copilot) for exposing tools to an agent over a wire protocol. A
*server* publishes tool descriptors and handles
invocations; Cantrip is the *client*. Configured servers
appear alongside Cantrip’s built-in tools as
`mcp__<server>__<tool>` — the agent
calls them the same way it calls
`read_file` or `juju_status`.

Useful MCP servers for a Juju-charm agent: Charmhub search,
Grafana PromQL/LogQL wrappers, GitHub org context, Launchpad bug
lookup, workload-specific introspection. See
[design/MCP_SERVERS.md](https://github.com/tonyandrewmeyer/cantrip/blob/main/design/MCP_SERVERS.md)
if you want to author one.

{#config-file}
## Where to configure

Cantrip reads two YAML files, in order:

1. **User scope:** `~/.config/cantrip/mcp.yaml`
   (override via `CANTRIP_MCP_USER_CONFIG`) — the
   right place for personal servers you want across every charm.
2. **Repo scope:** `cantrip.mcp.yaml` next
   to your charm directory — for project-specific servers
   that should be committed. Repo-scope values override user-scope
   on a name collision.

A malformed file is logged and skipped rather than crashing the
agent, so a typo in one place never takes the other down.

{#stdio}
## Add a stdio server

Stdio is the common case — Cantrip spawns the server as a
subprocess and talks to it over pipes. Example
`cantrip.mcp.yaml`:

```
servers:
  charmhub:
    command: uvx
    args: ["charmhub-mcp"]
    env:
      CHARMHUB_TOKEN: ${CHARMHUB_TOKEN}
    timeout_seconds: 30
    allowed_tools: ["search", "info"]
```

Every field is validated at load time:

- `command` is required for stdio.
  `args`, `env`, `cwd` are
  optional.
- `timeout_seconds` caps the per-call timeout. Default
  `30`.
- `allowed_tools` is a per-server allowlist. Empty
  means “expose every tool the server publishes”; a
  non-empty list surfaces only those names. This is the
  authoritative gate for MCP exposure — operators tighten
  access by editing the YAML, no code change needed.

Cantrip auto-starts every configured server on boot. Failures
land in per-server status (see [`/mcp`](#mcp-command))
so one broken server never blocks the healthy ones.

{#http}
## Add an HTTP server

For remote servers, use the streamable-HTTP transport:

```
servers:
  grafana:
    transport: http
    url: https://grafana.example.com/mcp
    headers:
      Authorization: "Bearer ${GRAFANA_TOKEN}"
    timeout_seconds: 60
```

`url` is required for HTTP. `headers` are
sent with every request. For servers that require OAuth rather
than a pre-shared token, see [OAuth](#oauth).

{#mcp-command}
## Inspect running servers with `/mcp`

Type slash commands directly in the chat (TUI or Web):

<pre><code><span class="comment"># Overview of every configured server:</span>
/mcp

<span class="comment"># Per-server tool list, with descriptions:</span>
/mcp tools charmhub

<span class="comment"># Full syntax help:</span>
/mcp help</code></pre>

Status markers:

- `[ok]` — connected, tools available.
- `[!!]` — failed to start or connect; hover for the error.
- `[--]` — stopped (after `stop_mcp`).
- `[..]` — pending (startup still in flight).

{#oauth}
## OAuth 2.1 for HTTP servers

Servers that require a user login use the SDK’s
`OAuthClientProvider`. Cantrip handles PKCE, dynamic
client registration, RFC 9728 Protected Resource Metadata
discovery, and token refresh — you just declare the server:

```
servers:
  charmhub-oauth:
    transport: http
    url: https://charmhub.example.com/mcp
    oauth:
      client_name: cantrip-prod
      scopes: ["repo", "publish"]
      redirect_port: 9876
```

On first connection Cantrip opens the authorisation URL in your
browser (via `webbrowser.open`) and binds a
single-purpose listener to
`http://127.0.0.1:<redirect_port>/callback`. The
listener captures one OAuth redirect, returns the
`code` and `state` to the SDK, and shuts
down. Successful authorisations store the tokens at
`~/.config/cantrip/mcp_tokens/<server>/`
(override with `CANTRIP_MCP_TOKEN_DIR`) at
`0600` so only your user can read them.

Want encryption at rest? Set
`CANTRIP_MCP_GPG_TOKENS=1` and Cantrip wraps every
write in `gpg --symmetric`. You need a configured
`gpg-agent` so writes don’t block on a passphrase
prompt.

If the OAuth provider uses its own published metadata document
(some servers don’t support dynamic client registration),
add `client_metadata_url:` to the `oauth`
block.

{#elicitation}
## Mid-task elicitation

Some MCP servers can pause a tool call to ask the user for
structured input — “which database name should I
create?”, “paste the verification code from your
email”. Cantrip bridges these through the UI event bus.
When a server requests elicitation:

1. Cantrip emits an `MCP_ELICITATION_REQUEST` event.
2. The TUI / Web renders the prompt.
3. Your answer flows back through
   `complete_mcp_elicitation`.

A bounded 600-second timeout auto-declines runaway requests so
a server can’t park the conversation forever.
*Interactive form rendering in the TUI/Web is still a
work-in-progress — the event is emitted today; the prompt
widget is a follow-up.*

{#marketplace}
## Discover servers via marketplaces

A marketplace is a catalogue of available MCP servers. Cantrip
reads `marketplace.json` files from three source kinds,
declared at the top level of `cantrip.mcp.yaml`:

<pre><code>marketplaces:
  <span class="comment"># Fetch from a GitHub repo's main branch:</span>
  - github: anthropic-ai/mcp-servers

  <span class="comment"># Read from a local directory (offline / corporate mirrors):</span>
  - directory: ~/work/canonical-mcp-catalog

  <span class="comment"># Arbitrary URL:</span>
  - url: https://example.com/marketplace.json</code></pre>

List what’s available:

<pre><code><span class="comment"># Show every server from every configured marketplace:</span>
/mcp marketplace

<span class="comment"># Bypass the 24-hour cache and re-fetch:</span>
/mcp marketplace refresh</code></pre>

Each entry shows its description, install hint, required env
vars, and OAuth scopes. **Cantrip never auto-installs a
server** — you copy the descriptor into your own
`cantrip.mcp.yaml` after reviewing it. This is
intentional: marketplaces are discovery surfaces, not trust
surfaces.

Override the marketplace cache directory with
`CANTRIP_MCP_MARKETPLACE_CACHE`. The default cache
sits at `~/.cache/cantrip/marketplaces/` with a 24-hour
TTL.

{#canonical-bundle}
## Canonical-native catalogue (Launchpad, Snapcraft, Charmcraft, MAAS)

Cantrip ships an example marketplace under
`examples/mcp/canonical/marketplace.json` covering four
highest-leverage Canonical surfaces — **Launchpad** (bug search,
merge proposals, project lookup), **Snapcraft** (snap search,
info, release-channel data), **Charmcraft**
(`lint`, `analyse`, plus opt-in
`register` / `upload` / `release`), and **MAAS** (machine
inventory and bare-metal provisioning for machine-substrate
charms — kernel modules, GPU passthrough, multi-NIC topologies).

Point your marketplace at the shipped directory to discover the
descriptors from inside Cantrip:

```
marketplaces:
  - directory: /path/to/cantrip/examples/mcp/canonical
```

Then `/mcp marketplace` lists each Canonical server with its
description and install hint. The MCP servers themselves
(`launchpad-mcp`, `snapcraft-mcp`,
`charmcraft-mcp`, `maas-mcp`) live in their own repositories;
Cantrip ships the client and the descriptor catalogue, not the
servers. `maas-mcp` is not yet published on PyPI; the descriptor
ships as a template that names the intended invocation, the same
way the Snapcraft and Charmcraft descriptors did before their
servers shipped.

### Safety story

Each server's tools split into a **read set** (safe by default)
and a **write set** (`allowed_tools`-gated). Cantrip's
authoritative gate is the per-server `allowed_tools`
list — an empty list exposes every tool the server publishes,
which is the wrong default for any server that ships publish or
capacity verbs.

| Server | Read (safe default) | Write (opt in via `allowed_tools`) | Credential |
| --- | --- | --- | --- |
| Launchpad | `bug_search`, `bug_view`, `merge_proposal_view`, `project_view` | `bug_comment`, `bug_status_set` | OAuth token |
| Snapcraft | `snap_search`, `snap_info`, `snap_releases` | `snap_register`, `snap_upload`, `snap_release` | `SNAPCRAFT_MACAROON` |
| Charmcraft | `lint`, `analyse` | `register`, `upload`, `release` | `CHARMHUB_MACAROON` |
| MAAS | `machine_list`, `machine_view`, `tag_search`, `subnet_list`, `pool_list`, `version` | `machine_acquire`, `machine_release`, `machine_deploy` | `MAAS_API_KEY` |

MAAS is the odd one out: the API requires authentication for
*every* call, so `MAAS_API_KEY` is needed for reads too — the
split is read vs write, not unauthenticated vs authenticated.
MAAS writes are also *capacity-changing* (acquiring removes a
machine from the shared pool, deploying writes an OS image to
physical hardware, releasing wipes and returns it), so the opt-in
posture should be the same as for any production-cloud capacity
verb.

The read-only starting point — copy this into the
`servers:` block of your `cantrip.mcp.yaml`:

```
servers:
  launchpad:
    command: uvx
    args: ["launchpad-mcp"]
    allowed_tools: ["bug_search", "bug_view", "merge_proposal_view", "project_view"]

  snapcraft:
    command: uvx
    args: ["snapcraft-mcp"]
    allowed_tools: ["snap_search", "snap_info", "snap_releases"]

  charmcraft:
    command: uvx
    args: ["charmcraft-mcp"]
    allowed_tools: ["lint", "analyse"]

  maas:
    command: uvx
    args: ["maas-mcp"]
    env:
      MAAS_API_KEY: ${MAAS_API_KEY}
    allowed_tools: ["machine_list", "machine_view", "tag_search", "subnet_list", "pool_list", "version"]
```

When you actually want the agent to publish a charm, file a
Launchpad comment, or acquire a MAAS machine, add the specific
write verb to `allowed_tools` and supply the credential.
Each call still goes through the user-confirmation gate as well:

```
servers:
  charmcraft:
    command: uvx
    args: ["charmcraft-mcp"]
    env:
      CHARMHUB_MACAROON: ${CHARMHUB_MACAROON}
    allowed_tools: ["lint", "analyse", "upload", "release"]

  maas:
    command: uvx
    args: ["maas-mcp"]
    env:
      MAAS_API_KEY: ${MAAS_API_KEY}
    allowed_tools: ["machine_list", "machine_view", "tag_search", "subnet_list", "pool_list", "version", "machine_acquire", "machine_release"]
```

The same pattern applies to Launchpad bug edits and Snapcraft
revisions — name the verb, supply the credential, leave everything
else off the list.

### How Cantrip uses these servers

Three of the catalogue's servers are wired into existing Cantrip
surfaces. Nothing changes for users without the catalogue
installed; the integrations only light up when the matching server
appears in the registry.

| Server | Surface | What changes |
| --- | --- | --- |
| `launchpad` | `/search-charms` | A third `## Launchpad (mcp__launchpad)` section appears under the Charmhub + Launchpad-REST results, populated from `project_lookup` and `bug_search`. Unpublished or in-progress Launchpad projects surface as first-class citations rather than being hidden behind a manual second search. |
| `snapcraft` | `list_inference_snaps` | Each enumerated snap is enriched with Snap Store metadata (publisher, summary, channels) via `snap_info`, rendered under a dedicated `Snap Store metadata (mcp__snapcraft)` section. Local discovery still drives "what's installed and reachable". |
| `charmcraft` | `charmlint` | After the built-in linter finishes, the charmcraft server's `lint` and `analyse` outputs are appended under a `Second opinion (mcp__charmcraft)` block. The local linter remains authoritative — a local failure short-circuits before the MCP call. |

Per-tool failures (a server that's unreachable mid-call, an
allowlist refusal, a tool the server doesn't advertise) render
inline within their section and never abort the surrounding
command.

For the `maas` server specifically — including the
capacity-allowlist opt-in and a worked machine-charm flow — see the
[Target a Canonical-cloud substrate](howto-substrates.html) how-to,
which also covers the OpenStack / Sunbeam and MicroCloud guidance
surfaces.

{#security}
## Security notes

- **Token files live at `0600` in a `0700`
  directory.** Add `CANTRIP_MCP_GPG_TOKENS=1`
  when you want encryption at rest.
- **Per-server allowlists are the authoritative MCP gate.**
  The agent’s task-category gate lets every
  `mcp__*` through by default; control exposure by
  editing `allowed_tools` in the YAML.
- **Marketplaces are read-only.** Nothing installs
  automatically — you review descriptors before copying
  them in.
- **Mid-task elicitation has a bounded timeout**
  (600 seconds by default). A runaway server can’t park
  your conversation.

{#troubleshooting}
## Troubleshooting

### “Server shows `[!!]` failed”

Run `/mcp` to see the failure reason. Common causes:

- Stdio command not on `PATH` — check with
  `which <command>`.
- Environment variable referenced with `${VAR}` is
  unset — Cantrip substitutes at spawn time and will log
  the blank.
- HTTP URL unreachable (DNS, firewall) — try
  `curl` first.
- OAuth redirect port already in use — set a different
  `redirect_port` in the `oauth` block.

### “Tools from a connected server aren’t visible to the agent”

Check the per-server `allowed_tools` list — a
non-empty list filters the exposed set. Empty means “allow
every tool the server publishes”. After editing the YAML
restart Cantrip; tool registration happens at boot.

### “OAuth hung on the redirect”

The localhost listener waits up to 5 minutes for the browser
callback. Check that a browser tab actually opened
(`webbrowser.open` silently fails on some headless
systems — Cantrip logs the authorisation URL so you can
copy it manually). Re-running the connection after a failure
starts a fresh flow.
