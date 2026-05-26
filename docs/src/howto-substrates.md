---
title: "How to target a Canonical-cloud substrate — Cantrip"
description: "Substrate-aware behaviour for MAAS, Canonical OpenStack / Sunbeam, and MicroCloud — how Cantrip detects each one, what changes in DESIGN.md and acceptance tests, and the boundary between agent automation and operator workflow."
h1: "Target a Canonical-cloud substrate"
subtitle: "MAAS for bare metal, Canonical OpenStack / Sunbeam for tenant clouds, and MicroCloud for compact private clouds — Cantrip adapts its guidance to the substrate the operator already runs."
section: howto
breadcrumb_label: "Substrate targets"
on_this_page:
  - { anchor: "vocabulary", label: "Substrate vocabulary stays binary" }
  - { anchor: "maas", label: "MAAS — bare-metal workloads" }
  - { anchor: "openstack", label: "OpenStack and Sunbeam" }
  - { anchor: "microcloud", label: "MicroCloud" }
  - { anchor: "boundary", label: "What Cantrip does and doesn't do" }
see_also:
  - label: "Configure MCP servers"
    href: "howto-mcp.html"
  - label: "The three charm paths"
    href: "explanation-charm-paths.html"
  - label: "Substrate design note"
    href: "https://github.com/tonyandrewmeyer/cantrip/blob/main/design/SUBSTRATES.md"
    external: true
---

{#vocabulary}
## Substrate vocabulary stays binary

Cantrip's primary substrate vocabulary is **`k8s`** versus **`machine`** —
the system prompt's path-A / B / C decision and the Concierge preset
matrix are both built around that split. MAAS, Canonical OpenStack /
Sunbeam, and MicroCloud are *refinements on the machine path*, not
peer enum members. The agent recognises them, surfaces relevant
guidance, and adapts acceptance tests; the operator still installs and
maintains them with the first-party tooling each substrate ships.

When Cantrip starts a session, the first system-prompt build probes
the local environment via `juju controllers` + `juju show-controller`
+ `snap list microcloud`, caches the result, and surfaces it as a
**`Substrate`** block inside the prompt's `Current Context`. The
block names the active controller's cloud, lists the registered
controllers, and flips two hints when applicable: **OpenStack target**
(active cloud is `openstack` or `sunbeam`) and **MicroCloud detected**
(`microcloud` snap installed locally). The rest of this page walks
through what changes when each hint fires.

{#maas}
## MAAS — bare-metal workloads

Reach for MAAS when the workload needs real hardware — kernel-module
charms, GPU passthrough, BMC-driven labs, multi-NIC topologies,
anything Juju's LXD provider can't reasonably stand in for. The
substrate-to-charm wiring already exists in Juju (`juju bootstrap
maas`); what was missing was the agent's awareness, and that is what
landed in Phases 97.2 / 97.3 / 97.4.

### Configure the MAAS MCP descriptor

The Canonical example catalogue ships a `maas` server descriptor
alongside Launchpad, Snapcraft, and Charmcraft. Point your
marketplace at the bundled directory to pick it up:

```
marketplaces:
  - directory: /path/to/cantrip/examples/mcp/canonical
```

Then `/mcp marketplace` lists `maas` with its description and install
hint. The MCP server itself (`maas-mcp`) lives in its own repository;
the descriptor ships as a template that names the intended invocation,
and writes go behind the operator's MAAS API key.

### Read-only baseline

Every MAAS API call requires authentication, so reads need the API
key too — the split is read vs write, not unauthenticated vs
authenticated. The read-only `cantrip.mcp.yaml` entry:

```
servers:
  maas:
    command: uvx
    args: ["maas-mcp"]
    env:
      MAAS_API_KEY: ${MAAS_API_KEY}
    allowed_tools:
      - machine_list
      - machine_view
      - tag_search
      - subnet_list
      - pool_list
      - version
```

With the read verbs in `allowed_tools`, the agent can ground
machine-charm design in real inventory ("we see 4 machines with the
`gpu` tag in pool `lab1`, the design assumes one per replica"). The
existing `analyse_framework` and planner flows pick this up
automatically when the controller is on a `maas` cloud.

### Capacity allowlist opt-in

Capacity-changing verbs (`machine_acquire`, `machine_release`,
`machine_deploy`) change shared pool capacity, so they stay off the
allowlist by default. When the operator wants the agent to acquire or
release machines, add the verbs explicitly:

```
servers:
  maas:
    command: uvx
    args: ["maas-mcp"]
    env:
      MAAS_API_KEY: ${MAAS_API_KEY}
    allowed_tools:
      - machine_list
      - machine_view
      - tag_search
      - subnet_list
      - pool_list
      - version
      - machine_acquire
      - machine_release
```

Each capacity call still goes through Cantrip's user-confirmation
gate; the allowlist is the second of two locks, not the first.

### A worked machine-charm flow

A typical bare-metal charm session, with the MCP descriptor wired up
and a MAAS-cloud Juju controller already registered:

1. **Describe the workload**: "build an operator for an out-of-tree
   kernel module — needs bare metal, the `gpu` MAAS tag, two NICs."
2. **Substrate decision**: the prompt's `Substrate` block names the
   `maas` cloud; the path-decision rule routes to **Path C
   (Infrastructure)** because the workload classifies as machine.
3. **Inventory grounding**: the agent calls `machine_list` and
   `tag_search` through the MCP gate, lists the candidate machines,
   and folds the result into DESIGN.md as concrete numbers rather
   than hand-waving ("the design targets 4 GPU-tagged machines in
   `lab1`").
4. **Deploy**: `juju deploy …` against the existing MAAS controller.
   Cantrip does **not** run `juju bootstrap maas` itself — the
   controller is the operator's responsibility.
5. **Acceptance**: the standard acceptance task plus MAAS-specific
   probes (the right machines were acquired, the NIC topology
   matches the design) once the operator has approved capacity verbs.

{#openstack}
## OpenStack and Sunbeam

OpenStack-shaped work in Cantrip is **guidance-only**. There is no
OpenStack MCP server in this phase, no Sunbeam installer wrapper, and
no agent-side tenant-admin tooling. The signal Cantrip needs is "the
active Juju controller is on cloud `openstack` or `sunbeam`", and the
agent reads that signal directly from `juju controllers`. (Sunbeam is
Canonical's opinionated OpenStack installer; the resulting cluster
registers as a Juju `openstack` cloud, so the OpenStack hint covers
both.)

### What turns on

When the substrate block flags `**OpenStack target**`, three things
change:

- **DESIGN.md callout** — the agent folds an `## OpenStack target`
  sub-section into DESIGN.md naming the storage class and ingress
  shape the charm should prefer (cinder-csi for persistent storage,
  neutron-api-backed ingress) and the resilience scenarios the
  acceptance task will probe (AZ loss, volume detach).
- **`preset-bundles` substrate refinements** — when the agent
  composes relations using a known preset (`cos-lite`,
  `twelve-factor-cos`, `identity-platform`), the skill's
  "Substrate refinements (Canonical clouds)" subsection points it at
  cinder-csi storage and neutron-api ingress rather than ephemeral
  storage and a node-port Service.
- **Extra acceptance task** — the autodeploy hook layers an
  `[Acceptance] verify against AZ loss and volume detach (OpenStack)`
  task on top of the base acceptance task. The task description
  asks the agent to drain one AZ (or stop the compute node hosting a
  unit), detach and reattach the persistent volume, and record
  outcomes under an `## OpenStack resilience` heading in
  `ACCEPTANCE.md`.

### What stays off

OpenStack tenant-admin operations — image upload, instance create /
destroy, volume management — are out of scope. The operator runs
`openstack` or `juju exec` themselves; Cantrip does not ship a
tenant-side OpenStack tool family. Likewise there is no
`sunbeam`-named Concierge preset: Sunbeam itself is an installer
with its own lifecycle, and operators who want Sunbeam run it first
and point Cantrip at the resulting Juju controller.

{#microcloud}
## MicroCloud

MicroCloud is the compact private-cloud substrate — LXD + MicroOVN +
MicroCeph + optional MicroK8s in one `microcloud init` command. The
right answer for HA-on-three-nodes, on-prem developer clusters, and
edge-lab demos where MAAS is overkill and a single LXD host is too
small.

### Detection, not provisioning

Cantrip does **not** drive `microcloud init`. The detection signal is
the presence of the `microcloud` snap on the same host as the
running LXD controller — a cheap `snap list microcloud` probe,
guarded so it short-circuits when `snap` itself is not on `PATH`.
When the probe hits, the substrate block flips the
`**MicroCloud detected**` hint and the agent adapts:

- **DESIGN.md** mentions MicroCloud as the production target in the
  Substrate section and recommends **MicroCeph** as the storage
  backend when the workload needs persistent storage.
- **Cross-controller COS** picks up the parallel **MicroK8s sibling
  cluster** that ships with MicroCloud automatically — the existing
  `_find_k8s_controller` path treats `microk8s` as a K8s cloud
  family, so COS lands there without microcloud-specific code.
- **Companion charms** named in the agent's `preset-bundles`
  recommendations reuse the MicroCeph + MicroK8s siblings rather
  than asking the operator to stand up a parallel LXD-only setup.

The detection is conservative — Cantrip only switches to
MicroCloud-aware guidance when there's a positive signal (the snap
is installed). Otherwise it falls back to single-host LXD guidance.

### What stays off

No `microcloud` Concierge preset, no installer wrapping, no
assumption that "LXD controller ⇒ MicroCloud". MicroCloud's install
path is interactive (`microcloud init` walks the operator through
cluster formation); wrapping it would be a parallel installer with
its own lifecycle, and Cantrip would lose robustness more than it
would gain.

{#boundary}
## What Cantrip does and doesn't do

The split between agent and operator is deliberate. Cantrip's
substrate-aware behaviour stays above the
[Concierge](https://github.com/canonical/concierge) boundary —
Concierge owns the install-LXD-and-bootstrap-a-controller story;
Cantrip owns the recommend-the-right-substrate-and-shape-the-charm
story.

| Substrate | Concierge owns | Cantrip owns above Concierge |
| --- | --- | --- |
| **LXD** | Install LXD snap; bootstrap LXD controller; install craft tools | Substrate recommendation, charm scaffolding |
| **Canonical K8s** | Install `k8s` snap; bootstrap K8s controller; deploy COS | Substrate recommendation, charm scaffolding, observability wiring |
| **MicroK8s** (legacy) | Install `microk8s` snap; bootstrap controller | Same as Canonical K8s, with the registry-add-on caveat in the system prompt |
| **MAAS** | *Nothing today* — Concierge has no MAAS preset | Detect existing MAAS controller; MCP-server-mediated machine inventory; substrate-aware design and runbook hints |
| **OpenStack / Sunbeam** | *Nothing today* — Concierge has no Sunbeam preset | Detect existing OpenStack controller; substrate-aware design, acceptance, and runbook hints |
| **MicroCloud** | *Nothing today* — Concierge has no MicroCloud preset | Detect MicroCloud-flavoured LXD controller (plus optional MicroK8s sibling); substrate-aware design and runbook hints |

MAAS, Sunbeam, and MicroCloud are production-shaped substrates that
operators install with their own first-party installers; if Concierge
upstream ever ships presets for any of them, the wiring on Cantrip's
side is small (one preset name, one cloud family entry, one
`_controller_matches_preset` update — about three lines, no parallel
abstraction).

Until then, the contract is: **the agent recommends and consumes; the
operator installs and maintains**.
