# Canonical MCP catalogue (example)

This directory ships an example `marketplace.json` describing four
Canonical-native MCP server surfaces — **Launchpad**, **Snapcraft**,
**Charmcraft**, and **MAAS**.  It exists so a user wanting to enable any
of these can copy a working descriptor instead of inventing one from
scratch.

The MCP servers themselves (`launchpad-mcp`, `snapcraft-mcp`,
`charmcraft-mcp`, `maas-mcp`) live in their own repositories — Cantrip
ships an MCP *client*, not the servers.  See
[`design/MCP_SERVERS.md`](../../../design/MCP_SERVERS.md) for the
authoring guide.

`maas-mcp` is not yet published on PyPI; the descriptor ships as a
template that names the intended invocation, the same way the Snapcraft
and Charmcraft descriptors did before their servers shipped.

## Discover the catalogue

Point Cantrip's MCP marketplace at this directory by adding the block
below to `~/.config/cantrip/mcp.yaml` (user scope) or `cantrip.mcp.yaml`
(repo scope):

```yaml
marketplaces:
  - directory: /path/to/cantrip/examples/mcp/canonical
```

Then list the catalogue from inside Cantrip:

```
/mcp marketplace
```

Each server appears with its description and install hint.  Nothing is
auto-installed — copy the descriptor you want into the `servers:` block
of your own `cantrip.mcp.yaml` and edit `allowed_tools` to taste.

## Safety story

The four Canonical surfaces split into **read** verbs (safe by default)
and **write** verbs (allowlist-gated).  Cantrip's authoritative gate is
the per-server `allowed_tools` list in `cantrip.mcp.yaml`: an empty list
means "expose every tool the server publishes"; a non-empty list filters
to exactly the named tools.

| Server | Read (safe default) | Write (opt in via `allowed_tools`) | Credential |
|---|---|---|---|
| Launchpad | `bug_search`, `bug_view`, `merge_proposal_view`, `project_view` | `bug_comment`, `bug_status_set` | OAuth token |
| Snapcraft | `snap_search`, `snap_info`, `snap_releases` | `snap_register`, `snap_upload`, `snap_release` | `SNAPCRAFT_MACAROON` |
| Charmcraft | `lint`, `analyse` | `register`, `upload`, `release` | `CHARMHUB_MACAROON` |
| MAAS | `machine_list`, `machine_view`, `tag_search`, `subnet_list`, `pool_list`, `version` | `machine_acquire`, `machine_release`, `machine_deploy` | `MAAS_API_KEY` |

The descriptor `description` fields in `marketplace.json` repeat the
read/write split so it surfaces in the `/mcp marketplace` listing too.

MAAS writes are *capacity-changing*, not *publish*: acquiring a machine
removes it from the available pool for other tenants, deploying writes
an OS image to physical hardware, and releasing wipes and returns it.
Treat the opt-in posture for MAAS writes the way you would treat any
production-cloud capacity verb, not the way you would treat a
charmhub-publish verb that only affects your own namespace.

## Copy-paste: read-only defaults

The safest starting point — search, lookup, lint, analyse — and nothing
that mutates remote state:

```yaml
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

The MAAS API key is needed for *every* MAAS call, including reads —
MAAS does not expose an anonymous endpoint.  The split here is read vs
write, not authenticated vs unauthenticated.

## Copy-paste: read + opt-in write

When you actually want the agent to file Launchpad comments, promote
a snap revision, or publish a charm, add the specific write verb to
`allowed_tools` and supply the credential.  The pattern is the same
as for any other destructive tool family — the agent will still go
through the user-confirmation gate on each call.

```yaml
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

Avoid the temptation to leave `allowed_tools` empty for a server that
exposes publish or capacity verbs.  Empty means "expose everything" —
including operations that change state on a remote registry or pull
machines out of a shared MAAS pool.
