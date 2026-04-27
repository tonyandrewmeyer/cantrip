---
title: "How to search the charm library — Cantrip"
description: "Use the Librarian subagent to find existing Charmhub and Launchpad charms before reinventing them."
h1: "Search the charm library"
subtitle: "Find existing Charmhub and Launchpad charms before building your own."
section: howto
breadcrumb_label: "Search the charm library"
see_also:
  - label: "How Cantrip works"
    href: "explanation-architecture.html"
  - label: "Agent tools"
    href: "reference-tools.html"
---

{#why}
## Why a Librarian subagent?

When the autonomous loop reaches a *Research* phase ("how should we
charm this LDAP service?"), the wrong answer is "build it from
scratch."  The right answer is "find the five most maintained existing
charms that already do this, and reuse what we can."

The **Librarian** is a read-only subagent.
It searches Charmhub and Launchpad in parallel, applies a quality
filter, and returns ranked excerpts with citations the primary agent
can paste into its design document.

{#what-it-does}
## What the Librarian can and can't do

The Librarian's tool whitelist is deliberately narrow:

| Tool | Purpose |
|---|---|
| `charmhub_search` | Full-text search across published charms; returns name, summary, publisher, channel risk, last-release date, and quality flags. |
| `charmhub_info` | Fetch a single charm's relations, config options, storage, and containers. |
| `charmhub_fetch` | Clone the charm's upstream Git repository (shallow) into the local cache for `read_file`/`grep`/`glob` inspection. |
| `launchpad_search` | Full-text search across Launchpad projects (catches unpublished or in-progress work). |
| `launchpad_fetch` | Clone a Git-hosted Launchpad project into the same cache (Bazaar projects are flagged but not auto-fetched). |
| `web_fetch`, `web_search` | Fallback for context that isn't in either catalogue. |
| `read_file`, `list_directory`, `grep`, `glob` | Browse the cache (the only filesystem the Librarian can touch). |

The Librarian **cannot** edit files, run commands, push branches, or
make any other state-changing call.  This makes it safe to run
unattended during research.

{#cache}
## Where the cache lives

Fetched sources land at `~/.cache/cantrip/charm-library/`:

```
~/.cache/cantrip/charm-library/
├── charmhub/
│   ├── postgresql-k8s/
│   │   ├── _cache_meta.json
│   │   ├── src/charm.py
│   │   └── …
│   └── redis-k8s/
│       └── …
└── launchpad/
    └── kafka-operator/
        └── …
```

The `_cache_meta.json` sidecar records the upstream URL, fetched-at
timestamp, and revision (for Charmhub).  Cached entries are reused
within 7 days; pass `force=true` to `charmhub_fetch`/`launchpad_fetch`
to refetch sooner.

Override the cache directory by setting `CANTRIP_CHARM_LIBRARY_DIR`
(useful in CI sandboxes that don't share `$HOME`).

{#manual}
## Search manually with `/search-charms`

The `/search-charms` slash command runs Charmhub and Launchpad search
in parallel and renders both result blocks together as Markdown:

<pre><code><span class="prompt">cantrip&gt;</span> /search-charms ldap sidecar</code></pre>

The output for each Charmhub hit carries quality flags so you can
spot stale or borderline candidates at a glance:

```
- **glauth-k8s** (databases) — LDAP server with REST config [by Canonical] [recently-maintained, channel-stable, publisher-canonical]
- **slapd-charm** — Older OpenLDAP charm [stale, channel-edge]
```

Quality flag vocabulary:

| Flag | Meaning |
|---|---|
| `recently-maintained` | At least one release in the last 12 months. |
| `stale` | No release in the last 12 months. |
| `channel-stable` / `channel-candidate` / `channel-beta` / `channel-edge` | Risk of the charm's default-release channel. |
| `publisher-canonical` / `publisher-verified` | Publisher carries a Charmhub validation badge. |
| `vcs-git` / `vcs-bazaar` | Launchpad project's VCS type. |

`/search-charms` is cheap — no source clone is triggered.  When you
need the source, ask the agent to call `charmhub_fetch <name>` or
`launchpad_fetch <name>` directly.

{#output-contract}
## The output contract

When the Librarian runs autonomously (the planner queues a `librarian`
task during Research), it writes its findings as Markdown using a
fixed shape so the primary agent can quote it verbatim:

```markdown
## glauth-k8s

- **source_url**: https://github.com/canonical/glauth-k8s-operator
- **why_this_matches**: Provides an LDAP backend over a Kubernetes
  sidecar with the same Pebble layer pattern we'd otherwise have to
  reinvent.
- **quality_flags**: recently-maintained, channel-stable, publisher-canonical
- **snippet**:

  > GLAuth charm bundles an LDAP server with REST configuration,
  > suitable for sidecar deployment alongside other Kubernetes
  > workloads.
```

Findings flow into the design document the primary agent assembles for
the user — every cited charm carries a real URL and an author-supplied
summary.

{#integration}
## When the Librarian runs automatically

During Research-phase work, the planner emits a `librarian` task
ahead of the operational-discovery synthesis when the workload's shape
suggests an existing charm could substitute.  The result lands as a
prior-task summary in the design subagent's prompt.

You don't have to do anything for this — the integration is opaque to
the user.  `/search-charms` is the manual override when you want to
double-check the agent's coverage or look up something during a
conversation.
