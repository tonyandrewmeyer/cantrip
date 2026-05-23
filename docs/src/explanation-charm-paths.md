---
title: "The three charm paths — Cantrip"
description: "Why Cantrip has three approaches to charm building and how it selects the right one for your workload."
h1: "The three charm paths"
subtitle: "Not all workloads are the same. Cantrip recognises three distinct categories and uses a different approach for each."
section: explanation
breadcrumb_label: "The three charm paths"
on_this_page:
  - { anchor: "why-three", label: "Why three paths?" }
  - { anchor: "path-a", label: "Path A: 12-factor PaaS" }
  - { anchor: "chiselled-rocks", label: "Chiselled rocks" }
  - { anchor: "path-b", label: "Path B: Custom applications" }
  - { anchor: "path-c", label: "Path C: Infrastructure" }
  - { anchor: "selection", label: "How the agent chooses" }
---

{#why-three}
## Why three paths?

A Flask web application and a PostgreSQL cluster have fundamentally
different operational requirements. A Flask app needs a container,
an ingress, and maybe a database relation. PostgreSQL needs
replication, failover, backup, point-in-time recovery, and careful
upgrade management.

Treating them the same would mean either over-engineering simple
applications or under-engineering complex ones. Cantrip addresses
this by selecting a charm path during the research phase, before
any code is written.

{#path-a}
## Path A: 12-factor PaaS applications

Path A is for stateless web applications that follow the
[twelve-factor](https://12factor.net/) methodology:
Flask, Django, FastAPI, Go HTTP servers, Express, Spring Boot.

These applications share a common pattern: they are containerised,
configured via environment variables, and fronted by a reverse
proxy. Canonical's `paas-charm` base handles all of
this with minimal custom code.

Path A is fast. The agent generates a `rockcraft.yaml`
to build the OCI image, configures the paas-charm base, wires up
ingress and COS, and deploys. For a simple application, this takes
under two minutes from description to active/idle.

### What you get

- OCI image via Rockcraft — chiselled (smaller, tighter) when the workload passes the eligibility check, or a fuller Ubuntu base when it does not
- paas-charm base with framework-specific configuration
- Ingress integration
- COS integration (traces, metrics)
- Config options mapped from environment variables

{#chiselled-rocks}
### Chiselled rocks

Cantrip can generate chiselled rocks for Path A workloads — OCI images
that contain only the filesystem slices the workload actually needs,
with no shell, no apt, and no unneeded OS utilities. The result is a
smaller image with a reduced attack surface and faster pulls.

Before generating a chiselled rock, Cantrip runs the
`check_chisel_eligibility` tool to verify that the workload does not
invoke a shell at runtime, does not call apt at runtime, and has no
opaque vendor install scripts. If the workload passes, Cantrip keeps
the default `base: bare` emitted by `rockcraft init` and adds a short
explanation to `rockcraft.yaml`. If the workload does not pass, Cantrip
falls back to `base: ubuntu@24.04` and explains why.

The escape hatch is always one line: change `base: bare` to
`base: ubuntu@24.04` in `rockcraft.yaml` to get the full Ubuntu
filesystem back.

{#path-b}
## Path B: Custom applications

Path B handles applications that do not fit the 12-factor model but
are not infrastructure software either. Examples include legacy
monoliths, applications with custom lifecycle management, or
workloads with unusual deployment requirements.

The agent scaffolds a full charm from scratch using the ops
framework, analyses the application's requirements, and generates
custom event handlers for install, config-changed, start, stop, and
any relations the application needs.

### What you get

- Full ops framework charm with custom handlers
- Application-specific config options and actions
- Relations tailored to the application's needs
- COS integration
- Unit and integration tests

{#path-c}
## Path C: Infrastructure software

Path C is for databases, message queues, caches, and other
stateful infrastructure. These workloads have complex operational
requirements: clustering, replication, leader election, failover,
backup and restore, scaling, and upgrade strategies.

Before writing any code, the agent checks Charmhub for existing
charms. If a production-quality charm already exists, the agent
recommends using it instead of building a new one. When a new charm
is warranted, the agent researches the software's operational
patterns in depth and proposes a comprehensive design covering
day-2 operations.

### What you get

- Full ops framework charm with operational complexity
- Clustering and replication support
- Backup and restore actions
- Scaling policies
- Upgrade and rollback procedures
- Comprehensive COS integration
- Extensive testing (unit, integration, chaos, scaling, upgrade)

{#selection}
## How the agent chooses

Path selection happens during the research phase. The agent:

1. Searches the web for information about the workload.
2. Uses the `analyse_framework` tool to detect the
   application type if source code is available.
3. Checks Charmhub for existing charms.
4. Evaluates the workload against path criteria: Does it follow
   12-factor patterns? Is it stateful infrastructure? Does it
   need custom operational logic?

The selected path is included in the design proposal. You can
override the choice — for example, telling the agent to use
Path B instead of Path A if you need more control over the charm's
event handlers.

See also:

- [How Cantrip works](explanation-architecture.html)
- [Observability and debugging](explanation-observability.html)
