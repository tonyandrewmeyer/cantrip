# Authoring MCP Servers for Cantrip

This document is the authoring guide for **MCP servers** that complement
Cantrip — Charmhub search/publish, Launchpad bug lookup, Loki/Prometheus
schema-aware wrappers, and similar Juju-ecosystem helpers.  Cantrip
ships an MCP **client** (Phase 45); the servers themselves live in
their own repositories so they can be developed, versioned, and
released independently of Cantrip's release cadence.

The aim here is to make it cheap for community or Canonical
contributors to publish a server that drops cleanly into Cantrip's
slash-command marketplace (`/mcp marketplace`) and gets used by
subagents alongside the built-in tools.


## Where servers live

Three options, all of which Cantrip understands without changes:

* **Their own repository** — each server is a small package
  (`charmhub-mcp`, `launchpad-mcp`, …) with its own README, tests, and
  release process.  Servers can live anywhere on GitHub or PyPI.
* **A companion bundle repository** — a single
  `tonyandrewmeyer/cantrip-mcp-servers` (or similar) with multiple
  servers under sub-directories.  Mirrors the
  [`microsoft/skills`](https://github.com/microsoft/skills) layout.
  Convenient for monorepo CI but couples release timing.
* **Within a charm itself** — when a server only makes sense for one
  charm (e.g. a custom database introspector), ship it in the charm's
  repo under `mcp/`.  Cantrip can consume it via the local
  `directory:` marketplace source.

Cantrip doesn't enforce any of these; the choice is purely about
distribution ergonomics.


## Anatomy of a server

Cantrip's client is a vanilla MCP client built on the official Python
SDK ([`mcp`](https://pypi.org/project/mcp/)).  Any server that
implements the protocol works — Python, Node, Go, Rust, anything else.
The Python SDK is the easiest starting point because the whole
protocol reduces to a pair of handlers:

```python
import mcp.types as types
from mcp.server import Server, ServerRequestContext
from mcp.server.stdio import stdio_server


async def list_tools(
    context: ServerRequestContext[None],
    params: types.PaginatedRequestParams | None,
) -> types.ListToolsResult:
    return types.ListToolsResult(
        tools=[
            types.Tool(
                name="search",
                description="Search Charmhub for charms matching a query.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "limit": {"type": "integer", "default": 10},
                    },
                    "required": ["query"],
                },
            ),
        ]
    )


async def call_tool(
    context: ServerRequestContext[None],
    params: types.CallToolRequestParams,
) -> types.CallToolResult:
    arguments = params.arguments or {}
    if params.name == "search":
        results = await charmhub_search(arguments["query"], arguments.get("limit", 10))
        return types.CallToolResult(
            content=[types.TextContent(type="text", text=results.as_markdown())]
        )
    return types.CallToolResult(
        content=[types.TextContent(type="text", text=f"unknown tool: {params.name}")],
        is_error=True,
    )


server = Server("charmhub-mcp", on_list_tools=list_tools, on_call_tool=call_tool)


async def main() -> None:
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
```

SDK 2.0 replaced the 1.x `@server.list_tools()` / `@server.call_tool()`
decorators with these constructor handlers, and renamed the model
fields to snake_case (`input_schema`, `is_error`, `requested_schema`).
The camelCase names survive as wire aliases, so a 1.x server keeps
interoperating — but 1.x *Python* server code no longer imports.

This stub already meets every Cantrip expectation: stdio transport,
JSON-Schema tool descriptors, Markdown text results.  The
`tests/unit/mcp_stub_server.py` in this repo is a working minimal
example to copy from.


## Tool design conventions

* **Names** — short, lowercase, snake_case.  Cantrip prefixes them with
  the server name automatically (`mcp__charmhub__search` etc.) so the
  bare name should describe the action only.
* **Descriptions** — one or two sentences, geared at the agent.  The
  description is the LLM's only hint about when to use the tool, so be
  specific: "Search Charmhub for charms matching a query.  Returns up to
  ``limit`` (default 10) matches as a Markdown table."
* **Schemas** — strict JSON Schema with `required` set explicitly.
  Cantrip's client passes the schema verbatim to the LLM; loose schemas
  produce sloppy tool calls.
* **Output** — prefer `TextContent` with Markdown over images or
  embedded resources.  Cantrip surfaces non-text parts as `[<type>]`
  placeholders, which is fine for fallback but not great for the
  agent's reasoning.
* **Errors** — raise from the handler (the SDK converts to an MCP error
  the client surfaces as `MCPInvocationError`) rather than returning a
  text result that says "error: …".  Strict separation keeps the
  agent's gating heuristics clean.
* **Side effects** — destructive operations should require a confirm
  flag (`confirm: bool` in the schema, default `false`).  The agent's
  built-in tools follow the same pattern; mirroring it keeps the
  interaction model uniform.


## marketplace.json

To make a server discoverable via `/mcp marketplace`, publish a
`marketplace.json` at the root of a GitHub repository (or under any
URL), with this shape:

```json
{
  "name": "canonical-mcp-servers",
  "description": "Juju-ecosystem MCP servers from Canonical.",
  "servers": {
    "charmhub": {
      "description": "Charmhub search, info, and publish.",
      "transport": "stdio",
      "command": "uvx",
      "args": ["charmhub-mcp"],
      "env_required": ["CHARMHUB_TOKEN"]
    },
    "launchpad": {
      "description": "Launchpad bug search and lookup.",
      "transport": "stdio",
      "command": "uvx",
      "args": ["launchpad-mcp"]
    },
    "grafana": {
      "description": "PromQL / LogQL schema-aware Grafana access.",
      "transport": "http",
      "url": "https://grafana-mcp.example.com",
      "scopes": ["query"]
    }
  }
}
```

Field reference:

| Field          | Type      | Required | Notes                                                  |
| -------------- | --------- | -------- | ------------------------------------------------------ |
| `description`  | string    | no       | Shown in `/mcp marketplace` listing                    |
| `transport`    | string    | no       | `stdio` (default) or `http`                            |
| `command`      | string    | stdio    | The command to spawn                                   |
| `args`         | string[]  | no       | Arguments to the command                               |
| `env_required` | string[]  | no       | Env vars the user must set; surfaced in the listing    |
| `url`          | string    | http     | The MCP HTTP endpoint                                  |
| `scopes`       | string[]  | no       | OAuth scopes (informational); surfaced in the listing  |

The user copies the descriptor they want into their own
`cantrip.mcp.yaml` and adds whatever local tweaks they need
(allowlist, env vars, OAuth config).  Cantrip never auto-installs.


## Authoring checklist

Before publishing a server:

- [ ] **Tool names** are short, snake_case, and describe the action.
- [ ] **Schemas** have `required` set on every necessary field.
- [ ] **Descriptions** explain *when* to use each tool, not just what
      it does.
- [ ] **Errors** raise from the handler; don't return text that says
      "error".
- [ ] **Destructive operations** require a `confirm` flag.
- [ ] **Output** is Markdown text content unless there's a real reason
      to use a different content type.
- [ ] **Stdio servers** test cleanly under
      `python -m your.server` — the SDK's `stdio_server()` context
      handles framing, but local stdio buffering can still bite.
- [ ] **HTTP servers** publish a Protected Resource Metadata (RFC 9728)
      document if they use OAuth.  Cantrip's `OAuthClientProvider`
      reads it via the SDK.
- [ ] **`marketplace.json`** describes the server (if you want it to
      appear in `/mcp marketplace`).


## Suggested servers

A non-exhaustive list of servers that would be valuable for Cantrip's
charm-building workflows.  None of these exist in this repo; they are
ideas worth a separate project.

| Server     | Tools                                                      | Justification                                       |
| ---------- | ---------------------------------------------------------- | --------------------------------------------------- |
| Charmhub   | `search`, `info`, `upload`, `release`                      | First-party charm registry; needed for Path C       |
| Launchpad  | `bug_search`, `bug_view`, `merge_proposal_view`            | Bug context for charm investigations                |
| Grafana    | `query_metrics`, `query_logs`, `dashboard_lookup`          | Schema-aware wrapper above raw `tempo_query`        |
| Snapcraft  | `snap_search`, `snap_info`                                 | Inference snap discovery (Phase 8 surface)          |
| Charmcraft | `lint`, `analyse`                                          | Local charmcraft sub-tools the LLM tends to forget  |
| MAAS       | `machine_list`, `machine_release`                          | Machine-charm dev environments                      |

Anyone shipping one of these can register it in a marketplace
(`marketplaces:` block in `cantrip.mcp.yaml`) and Cantrip's
`/mcp marketplace` will list it for end users.


## Safety defaults for the Canonical bundle

`examples/mcp/canonical/marketplace.json` ships an example catalogue
for the four highest-leverage Canonical surfaces — Launchpad,
Snapcraft, Charmcraft, and MAAS.  The catalogue is `directory:`-loadable
without any external network, so a user can copy a working descriptor
without inventing one from scratch.

The Canonical bundle splits each server's tools into a read set (safe
by default) and a write set (allowlist-gated).  Cantrip's authoritative
gate is the per-server `allowed_tools` list in `cantrip.mcp.yaml`: an
empty list exposes every tool the server publishes; a non-empty list
filters to exactly the named tools.  The marketplace descriptor's
`description` field repeats the split so the policy surfaces in the
`/mcp marketplace` listing.

| Server     | Read (safe default)                                                                       | Write (opt in via `allowed_tools`)                       | Credential           |
| ---------- | ----------------------------------------------------------------------------------------- | -------------------------------------------------------- | -------------------- |
| Launchpad  | `bug_search`, `bug_view`, `merge_proposal_view`, `project_view`                           | `bug_comment`, `bug_status_set`                          | OAuth token          |
| Snapcraft  | `snap_search`, `snap_info`, `snap_releases`                                               | `snap_register`, `snap_upload`, `snap_release`           | `SNAPCRAFT_MACAROON` |
| Charmcraft | `lint`, `analyse`                                                                         | `register`, `upload`, `release`                          | `CHARMHUB_MACAROON`  |
| MAAS       | `machine_list`, `machine_view`, `tag_search`, `subnet_list`, `pool_list`, `version`       | `machine_acquire`, `machine_release`, `machine_deploy`   | `MAAS_API_KEY`       |

The default posture is therefore "discovery and inspection without
credentials"; any tool that mutates remote state has to be named
explicitly in `allowed_tools` and supplied with its credential
environment variable.  This mirrors the destructive-operation gate that
Cantrip applies to its own built-in tools — empty `allowed_tools` is
the wrong default for a server that exposes publish or capacity verbs.

MAAS is the odd one out in two ways.  First, the API requires
authentication for every call, so the `MAAS_API_KEY` credential is
needed for reads too — the split is *read vs write*, not
*unauthenticated vs authenticated*.  Second, MAAS writes are
*capacity-changing*: `machine_acquire` removes a machine from the
available pool for other tenants, `machine_deploy` writes an OS image
to physical hardware, and `machine_release` wipes and returns it.  The
allowlist posture for MAAS writes should be the same as for any
production-cloud capacity verb, not the looser one that's reasonable
for charmhub-publish verbs that only affect your own namespace.

Phase 97.2 chose the MCP-first shape for MAAS deliberately: MAAS already
exposes a stable HTTP API and a Python client, the read verbs are a
near-mechanical port of the Phase 95.2 Launchpad / Snapcraft / Charmcraft
pattern, and Cantrip's deploy-side wiring for a MAAS-cloud Juju
controller is already in place (`_controller_matches_preset("machine",
"maas")` accepts it).  No built-in MAAS tool family — the API surface
belongs in an out-of-tree MCP server with its own release cadence.

Authors of new Canonical-adjacent servers should follow the same shape:
declare a clear read/write split in the description text, and document
which verbs require which credentials.  Cantrip does not impose
additional safety machinery on top of the allowlist; the
`/mcp marketplace` listing and this design note are the only places the
policy is recorded, so making it visible at the server boundary matters.


## Testing servers locally

Before publishing, point Cantrip at the directory containing the
server's `marketplace.json`:

```yaml
# ~/.config/cantrip/mcp.yaml
marketplaces:
  - directory: ~/work/my-mcp-server
servers:
  test-server:
    command: uv
    args: ["run", "python", "-m", "my_server"]
    cwd: ~/work/my-mcp-server
```

Then in Cantrip:

```
/mcp                  # Verify the server connects.
/mcp tools test-server   # Confirm Cantrip sees the tool list.
/mcp marketplace      # Confirm the marketplace entry appears.
```

Iterate locally; publish the marketplace.json once the descriptors
match what users will see.


## Related design docs

- [`design/TOOLS.md`](TOOLS.md) — Cantrip's built-in tool abstraction
  that MCP tools coexist with.
- [`design/SKILLS.md`](SKILLS.md) — On-demand instruction loading,
  often a complement to MCP tool exposure.
- [`design/PLAN.md`](PLAN.md) — Overall architecture and where MCP
  fits.
