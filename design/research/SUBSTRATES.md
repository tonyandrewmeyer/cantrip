# Canonical Cloud Substrates — MAAS, OpenStack / Sunbeam, MicroCloud

> Output of Phase 97.1.  This is a design note, not a research log:
> it decides the role each substrate plays inside Cantrip's existing
> environment story and how each relates to Concierge.  The
> downstream sub-phases (97.2 MAAS, 97.3 OpenStack / MicroCloud
> profiles, 97.4 examples and docs) implement against the decisions
> recorded here.

## TL;DR

- **Concierge stays the only environment provisioner Cantrip
  launches.**  We do not fork Concierge, write a parallel MAAS / Sunbeam
  / MicroCloud installer, or teach Cantrip to drive those products'
  setup commands directly.  Cantrip's role on these substrates is
  *consume*, not *install*.
- **Roles for the three substrates differ on purpose:**
  - **MAAS** is *machine inventory and provisioning*.  Cantrip uses
    it through Juju (`juju bootstrap maas` / `juju deploy --to`) plus
    an MCP server for the agent-visible read / prepare verbs
    (`machine_list`, `machine_release`, etc.).
  - **OpenStack / Sunbeam** is *a target cloud for IaaS-shaped charms
    and Canonical-cloud demos*.  Cantrip's job is to recognise it as
    a valid `machine` substrate, tailor design / acceptance guidance,
    and prefer the OpenStack-aware companion charms when relevant.
  - **MicroCloud** is *a compact private-cloud / edge lab*.  Cantrip's
    job is to recognise its multi-substrate shape (LXD + optional
    Kubernetes via MicroK8s + MicroOVN + MicroCeph) and route to the
    right Juju cloud, not to install it.
- **The user-visible substrate vocabulary stays binary** —
  `k8s` vs `machine`.  Refinements (MAAS / OpenStack / MicroCloud)
  ride on `machine` as a cloud-type detail surfaced in DESIGN.md,
  acceptance plans, and runbooks.  Adding a third top-level option
  would fight the rest of the prompt, the Concierge preset matrix,
  and Cantrip's path A/B/C vocabulary.
- **First agent-side surface** per substrate, in priority order:
  1. **MAAS:** a Canonical-bundle MCP descriptor (read verbs safe by
     default; capacity-changing verbs allowlist-gated), plus a small
     amount of system-prompt guidance teaching the agent when MAAS is
     a better fit than local LXD.  Mirrors the Phase 95.2 / 95.3
     pattern verbatim.
  2. **OpenStack / Sunbeam:** substrate-aware *guidance* — DESIGN.md
     section, machine-charm preset hints, acceptance-test
     adjustments.  No new tooling.
  3. **MicroCloud:** detection + routing.  When the agent sees a
     pre-bootstrapped microcloud-flavoured controller (cloud type
     `lxd`, but with the well-known multi-node shape), treat it as
     a first-class `machine`-substrate target rather than emitting a
     generic LXD runbook.  No installer, no preset.
- **What this note does not commit to:** a Concierge preset for
  MAAS, OpenStack, or MicroCloud.  Concierge upstream owns its preset
  matrix; if and when it adds them, Cantrip threads the preset name
  through `preflight.DEFAULT_PRESET` matching and the existing
  `_controller_matches_preset` table.  Until then we lean on
  `juju bootstrap <cloud>` against a pre-existing controller, exactly
  the way Cantrip already handles MAAS-as-machine today.

## 1. Scope

Phase 97 covers three Canonical substrate surfaces called out as
*high-value next additions* in
[`design/CANONICAL_SHOWCASE.md`](CANONICAL_SHOWCASE.md) §4.2:

- **MAAS** — bare-metal provisioning and machine inventory.
- **OpenStack / Sunbeam** — Canonical's private-cloud product,
  with Sunbeam as the opinionated installer / lifecycle manager.
- **MicroCloud** — Canonical's compact private-cloud product
  (LXD + MicroOVN + MicroCeph + optional MicroK8s), aimed at
  single-node and small-cluster labs.

Out of scope for Phase 97:

- Public-cloud substrates (AWS, GCP, Azure) — Juju already supports
  them and Cantrip does not currently treat them as a Canonical
  showcase.
- Bootstrapping Canonical OpenStack or MicroCloud from scratch.
  Those are first-party products with their own installers; the
  Canonical / Cantrip split-of-concerns puts substrate setup on the
  operator, not the agent.
- Adding a third top-level substrate enum to the system prompt.
  See §6.

## 2. Cantrip baseline

What Cantrip already does about substrate today, established by
walking the code that drives substrate decisions:

| Surface | Current behaviour | Source of truth |
|---|---|---|
| Concierge preset enum | `dev`, `machine`, `k8s`, `microk8s`, `crafts` | `concierge` skill at `src/cantrip/skills/concierge/SKILL.md` |
| Default preset | `k8s` (most common, fast to re-bootstrap to machine) | `DEFAULT_PRESET = "k8s"` in `src/cantrip/agent/preflight.py:41` |
| Cloud-family classification | `k8s` ∪ `microk8s` ∪ `kubernetes` ∪ `canonical-k8s` ⇒ K8s; everything else ⇒ machine | `_K8S_CLOUDS` in `preflight.py` and `tools/environment.py` |
| Preset / controller match | `_controller_matches_preset(preset, cloud)`: `k8s` preset needs K8s family; `machine` preset needs anything else | `tools/environment.py:111` |
| User-visible substrate vocabulary | `k8s` vs `machine` | system prompt §Substrate; `tools/planning.py:198`; DESIGN.md template |
| Substrate decision rule | 12-factor (Path A) ⇒ K8s; Path B/C uses Dockerfile / cloud-native / stateless ⇒ K8s; bare metal / GPU / kernel modules / systemd ⇒ machine; otherwise default K8s; confirm with the user | `src/cantrip/agent/prompts/system.md.j2:629` |
| Substrate names *mentioned* in prose | "IAAS (LXD/MAAS/etc.)" error string; "MAAS, openstack" in the planner tool's CAAS/IAAS comment | `tools/environment.py:254`; `tools/planning.py:198` |

The shorter form: **the abstraction is already binary, the machine
side is already a catch-all, and the named substrates already
overflow that catch-all.**  Nothing in §3 below changes that;
everything refines the catch-all.

## 3. Per-substrate role

### 3.1 MAAS

**Role:** machine inventory / provisioning for charms that need real
hardware — kernel-module workloads, GPU passthrough, BMC-driven
labs, multi-NIC network topologies, anything Juju's LXD provider
can't reasonably stand in for.

**Why MAAS specifically:**

- Juju already has a first-class MAAS cloud type (`juju bootstrap
  maas`), so the substrate-to-charm story is already wired — what's
  missing is the agent's *awareness* that MAAS is the right answer
  for some workloads.
- MAAS exposes a stable HTTP API and a Python client; an MCP server
  that wraps the read verbs (`machine_list`, `machine_view`,
  `tag_search`, `subnet_list`, `pool_list`) plus opt-in capacity
  verbs (`machine_acquire`, `machine_release`, `machine_deploy`) is
  a near-mechanical port of the Phase 95.2 / 95.3 Canonical-bundle
  pattern.  MCP_SERVERS.md already lists MAAS as a future surface
  (line 209: `machine_list`, `machine_release`).

**Default posture:**

- Read verbs (machine inventory, tag / subnet inspection) are safe
  by default and visible in `/mcp marketplace` listings the same way
  the Phase 95.2 catalogue is.
- Capacity-changing verbs (`machine_acquire` / `machine_release` /
  `machine_deploy`) are allowlist-gated via `allowed_tools` in
  `cantrip.mcp.yaml` and require an explicit MAAS API key.  Same
  shape as Launchpad / Snapcraft / Charmcraft writes.

**What Cantrip does at design time:**

- When the workload research surfaces "bare-metal / kernel / GPU /
  multi-NIC / BMC", the DESIGN.md "Substrate" section mentions
  MAAS as the production target alongside the K8s-or-machine
  decision.  The system-prompt substrate rule in
  `system.md.j2:629` gains a fifth bullet: *"bare metal or
  hardware-specific provisioning → machine, with MAAS as the
  production substrate."*
- When a MAAS MCP server is configured *and* the workload is a
  machine-substrate fit, `analyse_framework` / the planner uses
  `machine_list` to ground the design — e.g., "we see 4 machines
  with the `gpu` tag in pool `lab1`, the design assumes one
  per replica."

**What Cantrip does at deploy time:**

- If the user already has a MAAS-cloud Juju controller registered
  (`juju controllers` reports `cloud: maas`), Cantrip treats it as
  a valid `machine` controller and the existing
  `_controller_matches_preset("machine", "maas")` path already
  accepts it — no code change needed on the deploy side.
- Cantrip does **not** drive `juju bootstrap maas` itself in Phase
  97.  Bootstrap on a real MAAS region needs region credentials,
  IPMI access, and DHCP / PXE wiring that belong to the operator,
  not the agent.

**What Cantrip explicitly does not do:**

- No Concierge MAAS preset.  Concierge upstream does not currently
  ship one; if it adds `--preset maas` later we thread the name
  through `_controller_matches_preset` and the docs.
- No MAAS region / rack installer.  Cantrip cannot stand up a MAAS
  cluster from a fresh Ubuntu host; it consumes one.
- No "let's release every machine in the pool" affordances.
  Capacity verbs run only through the explicit `allowed_tools`
  allowlist and only when the operator opted in.

### 3.2 OpenStack / Sunbeam

**Role:** a target cloud for IaaS-shaped charms and Canonical-cloud
demos.  Most useful when the workload is an OpenStack tenant
service (instances, volumes, networks) or when the operator's
production substrate *is* a Canonical-OpenStack cloud and the
charm needs to be acceptance-tested there.

**Why OpenStack specifically:**

- Juju has a native OpenStack cloud type
  (`juju add-cloud openstack`, `juju bootstrap openstack`), so as
  with MAAS the deploy-side wiring is already there.
- Sunbeam is Canonical's opinionated OpenStack installer; if the
  operator runs Sunbeam, the resulting cluster registers cleanly as
  a Juju OpenStack cloud — no Sunbeam-specific wiring needed on the
  Juju side.
- Canonical-cloud demos benefit from a charm that *knows* it's
  landing on OpenStack: storage class hints, network topology
  hints, multi-AZ resilience guidance.

**Default posture:**

- **Guidance, not tooling, in Phase 97.**  No OpenStack MCP server,
  no Sunbeam installer wrapper.  The signal Cantrip needs is "the
  current Juju controller is on cloud `openstack`", which is
  already in `juju controllers --format=json`.
- DESIGN.md gains an "OpenStack target" callout when the controller
  cloud is `openstack`, the workload classifies as Path B / Path C,
  and the user has not explicitly said "build for K8s anyway".
- Acceptance-test guidance (`design/CHECKS.md` style) adds an
  OpenStack-on-Juju checklist: prefer cinder-storage, surface
  neutron-api integration if the workload exposes a service, run
  acceptance against more than one nova-compute unit when the
  workload claims AZ-awareness.

**What Cantrip does at design time:**

- When the active Juju controller's cloud is `openstack`, the
  planner emits an extra acceptance / runbook task: "verify against
  OpenStack-specific failure modes (volume detach, AZ loss)."
- The `preset-bundles` skill gains a Sunbeam-flavoured bundle hint
  for charms that benefit from canonical-OpenStack defaults
  (cinder-csi, etc.); the bundle itself is not generated, just
  cited as a starting point.

**What Cantrip explicitly does not do:**

- No `sunbeam`-named Concierge preset.  Concierge upstream's preset
  matrix does not include Sunbeam; Sunbeam itself is a separate
  installer with its own lifecycle.  If the operator wants Sunbeam,
  they run Sunbeam, then point Cantrip at the resulting Juju
  controller.
- No agent-side OpenStack capacity manipulation (instance create /
  destroy / image upload).  Those are tenant-admin operations and
  belong to the operator.
- No multi-substrate "Sunbeam + COS + ingress all wired together"
  bundle in Phase 97.  That kind of opinionated assembly belongs in
  a follow-up phase if there's user demand.

### 3.3 MicroCloud

**Role:** a compact private-cloud / edge lab — the production
analogue of "I have one beefy box and I want a Canonical-blessed
cluster on it".  Often the right answer for HA-on-three-nodes,
on-prem-developer-cluster, and edge-lab demos where MAAS is
overkill and a single LXD host is too small.

**Why MicroCloud specifically:**

- MicroCloud bundles LXD + MicroOVN + MicroCeph + optional
  MicroK8s into a one-command install (`microcloud init`).  Each
  component already has a Juju cloud type — LXD natively, MicroK8s
  via the `microk8s` cloud, MicroCeph via storage integrations on
  the LXD controller.
- For Cantrip this means *no new Juju cloud type, no MCP server, no
  installer wrapping*.  The substrate-aware piece is **recognising**
  MicroCloud (a multi-node LXD cluster with the MicroOVN /
  MicroCeph snap fingerprint) and routing accordingly.

**Default posture:**

- **Detection + routing, not provisioning, in Phase 97.**  Cantrip
  treats a microcloud-flavoured controller as a valid `machine`
  controller today, the same way it treats a single-host LXD
  controller.  The refinement is awareness of *MicroCloud-specific
  features* — MicroCeph storage classes, MicroOVN network zones,
  the embedded MicroK8s as a parallel `caas` cloud — so design
  notes and runbooks call them out instead of suggesting a parallel
  LXD-only setup.
- The companion MicroK8s cluster *is* a CAAS cloud and is detected
  by the existing K8s-cloud-family check in
  `preflight._find_k8s_controller`; no new code path is needed for
  Cantrip's cross-controller COS deployment to use it.

**What Cantrip does at design time:**

- When the active controller is `lxd` and the host advertises the
  MicroCloud snap, the DESIGN.md "Substrate" section mentions
  MicroCloud as the production target and recommends MicroCeph for
  persistent storage when the workload needs it.
- When a parallel MicroK8s controller exists (cloud type
  `microk8s`, snap fingerprint matches), the existing cross-
  controller COS path picks it for COS automatically — no
  microcloud-specific code, just the existing
  `_find_k8s_controller` reuse.

**What Cantrip explicitly does not do:**

- No `microcloud` Concierge preset.  MicroCloud's install path is
  `microcloud init`, which is an interactive cluster-formation
  flow; wrapping it in Concierge would be a parallel installer.
  If Concierge upstream adopts a microcloud preset later, we adopt
  it then.
- No assumption that "LXD controller ⇒ MicroCloud".  The detection
  is conservative — Cantrip only switches to MicroCloud-aware
  guidance when there's a positive signal (snap presence, multi-
  node membership, MicroCeph or MicroOVN visible to LXD).
  Otherwise it falls back to single-host LXD guidance.

## 4. Relationship to Concierge

Concierge is, and remains, the single environment-provisioner
Cantrip launches.  This phase's substrate decisions sit cleanly
above that boundary:

| Substrate | Concierge owns | Cantrip owns above Concierge |
|---|---|---|
| **LXD** (today) | Install LXD snap; bootstrap LXD controller; install craft tools | Substrate recommendation, charm scaffolding |
| **Canonical K8s** (today) | Install `k8s` snap; bootstrap K8s controller; deploy COS | Substrate recommendation, charm scaffolding, observability wiring |
| **MicroK8s** (today, legacy) | Install `microk8s` snap; bootstrap controller | Same as above, with the registry-add-on caveat already in the system prompt |
| **MAAS** (Phase 97) | *Nothing today* — Concierge has no MAAS preset | Detect existing MAAS controller; MCP-server-mediated machine inventory; substrate-aware design / runbook hints |
| **OpenStack / Sunbeam** (Phase 97) | *Nothing today* — Concierge has no Sunbeam preset | Detect existing OpenStack controller; substrate-aware design / acceptance / runbook hints |
| **MicroCloud** (Phase 97) | *Nothing today* — Concierge has no MicroCloud preset | Detect MicroCloud-flavoured LXD controller (+ optional MicroK8s sibling); substrate-aware design / runbook hints |

The split is deliberate.  Concierge's job is to *make a fresh
Ubuntu box developable*.  MAAS / Sunbeam / MicroCloud are
production-shaped substrates that operators install with their own
first-party installers and their own lifecycle commitments;
Cantrip would gain nothing — and lose a lot of robustness — by
trying to install them itself.

If Concierge upstream adds presets for any of these substrates in
the future, the wiring on Cantrip's side is small:

1. Add the preset name to the Concierge skill table at
   `src/cantrip/skills/concierge/SKILL.md` so the agent surfaces it
   in `concierge prepare --help`-shaped guidance.
2. Add the matching cloud family to `_K8S_CLOUDS` (if relevant) or
   leave the cloud in the implicit "everything else is machine" set.
3. Extend `_controller_matches_preset` to map the preset onto its
   cloud family explicitly, so the safety check in
   `tools/environment.py:111` and `preflight._is_already_provisioned`
   doesn't refuse a healthy matching controller.

That's all.  Adding a substrate via this path is two edits and a
table entry, with no parallel abstraction.

## 5. Agent-side surfaces

What 97.2 / 97.3 / 97.4 implement, in priority order:

### 5.1 MAAS (Phase 97.2)

Highest-leverage of the three: it gives the agent a new first-party
catalogue to ground machine-charm work, and the implementation is a
near-mechanical port of the Phase 95.2 / 95.3 Canonical-bundle MCP
pattern.

- **Marketplace descriptor.**  Extend
  `examples/mcp/canonical/marketplace.json` with a `maas` entry
  using the same shape as `launchpad` / `snapcraft` / `charmcraft`:
  `transport: stdio`, `command: uvx`, `args: ["maas-mcp"]`,
  `description` that names the read / write split.
- **Per-server safety story.**  Read verbs (`machine_list`,
  `machine_view`, `tag_search`, `subnet_list`, `pool_list`,
  `version`) safe by default; capacity verbs (`machine_acquire`,
  `machine_release`, `machine_deploy`) opt-in via
  `allowed_tools` with a `MAAS_API_KEY` credential.  Mirror the
  safety table in `design/MCP_SERVERS.md`'s "Safety defaults for
  the Canonical bundle" section and in the catalogue README.
- **Agent-side adoption.**  When a MAAS server is configured and
  the workload classifies as machine, the planner enriches design
  / runbook tasks with MAAS-grounded facts ("4 machines with `gpu`
  tag available"); when the substrate is *un*decided, MAAS presence
  is a hint toward `machine`.
- **Prompt nudge.**  One sentence in `system.md.j2:629`'s substrate
  rule: "bare metal or hardware-specific provisioning → machine,
  with MAAS as the production substrate when an MAAS controller or
  MCP server is available."
- **No upstream MAAS MCP server today.**  `uvx maas-mcp` is the
  intended invocation, but no published `maas-mcp` package exists
  on PyPI yet; the descriptor ships as a *template* that names the
  command path, exactly the way the Snapcraft / Charmcraft
  descriptors did before their tools shipped.

### 5.2 OpenStack / Sunbeam (Phase 97.3)

Guidance-shaped, not tool-shaped.  The implementation is
deliberately small:

- **Controller-cloud detection.**  Extend the planner's
  environment-summary input to include `juju controllers`'
  cloud-name field (already exposed by `list_controllers()` in
  `preflight.py:635`).  When `cloud == "openstack"`, the planner
  emits an "OpenStack target" sub-design note in DESIGN.md and an
  acceptance task ("verify against AZ loss and volume detach").
- **`preset-bundles` skill hint.**  Add a "running on Canonical
  OpenStack / Sunbeam?" callout that suggests the cinder-csi
  storage class and the neutron-api ingress shape for relevant
  charms.  No bundle generation; cite, don't assemble.
- **No MCP server in Phase 97.**  An OpenStack-tenant MCP surface
  (image upload, instance lifecycle) is a separate decision; the
  default posture above is "tenant operations belong to the
  operator".

### 5.3 MicroCloud (Phase 97.3)

Detection + routing.  Implementation:

- **Controller-cloud fingerprint.**  Extend
  `list_controllers()` callers (planner, preflight, system-prompt
  environment summary) to also report when the LXD host has the
  `microcloud` snap installed (cheap `snap list microcloud` check
  guarded by `shutil.which("snap")`).  When the fingerprint hits,
  surface "MicroCloud detected" alongside the cloud name in the
  agent's environment context.
- **Sibling-cluster reuse.**  No new code for MicroK8s; the
  existing `_find_k8s_controller` in `preflight.py:619` already
  walks `juju controllers --format=json` for any K8s-family cloud,
  so a parallel `microk8s` controller installed by MicroCloud is
  picked up for cross-controller COS automatically.
- **Design-time hint.**  When MicroCloud is detected, DESIGN.md's
  "Substrate" section mentions MicroCeph as the recommended
  storage backend for stateful workloads and notes the parallel
  MicroK8s sibling cluster for K8s components.

### 5.4 Examples and docs (Phase 97.4)

- **Worked MAAS example.**  A `docs/src/howto-maas.md` (rendered to
  `docs/docs/howto-maas.html`) showing the read-only MCP descriptor,
  the capacity-allowlist opt-in, and a one-shot machine-charm
  generation flow that references real machine inventory.
- **Worked OpenStack or MicroCloud example.**  One *or* the other,
  not both, in the initial drop.  Pick the one with a user-reported
  need first; if neither has user pull, default to MicroCloud (the
  smaller, more self-contained demo substrate).
- **Boundary documentation.**  Add a "what Cantrip does and doesn't
  do on each substrate" matrix to whichever howto page is
  authored, lifted verbatim from §4 above.  The agent recommends
  and consumes; the operator installs and maintains.

## 6. What this design rules out

- **A third top-level substrate enum.**  The prompt vocabulary
  stays `k8s` / `machine`.  Adding `maas` / `openstack` /
  `microcloud` as peer options would fight the rest of the prompt
  (path A/B/C, the Concierge preset matrix, the K8s-vs-machine
  rule of thumb), force every existing call site that switches on
  substrate to grow a third branch, and force users to think about
  a distinction (machine-LXD vs machine-MAAS) that doesn't change
  the charm shape until very late.  The refinement is *substrate
  detail on the machine path*, not a peer to it.
- **A Concierge fork or wrapper.**  Cantrip imports the Concierge
  preset matrix; it doesn't replace it.  If Concierge gains new
  presets we adopt them; we don't ship a parallel installer.
- **A Sunbeam, MicroCloud, or MAAS installer.**  Cantrip does not
  drive `microcloud init`, does not run `sunbeam cluster bootstrap`,
  and does not configure MAAS region controllers.  These are
  operator workflows with their own lifecycle and their own first-
  party tooling.
- **A tenant-side OpenStack tool family.**  Image upload, instance
  create / destroy, volume management — these are tenant-admin
  operations and stay outside Cantrip's tool catalogue.  A user
  who wants them runs `openstack` or `juju exec` themselves.
- **Bypassing Concierge in any environment that already has it.**
  When Concierge is installed and a healthy controller exists,
  Cantrip uses Concierge's preset-aware idempotency
  (`_is_already_provisioned` in `tools/environment.py:147`) the
  same way it does today.  MAAS / OpenStack / MicroCloud detection
  runs *above* that check, not in place of it.

## 7. Bottom line

The right shape for Phase 97 is **substrate-aware behaviour, not
substrate provisioning**.  Cantrip already has a Concierge-mediated
provisioning surface that operators trust; what's missing is the
agent's awareness that bare-metal / Canonical-cloud / compact-
private-cloud substrates exist, when they're the right answer, and
what changes about the generated charm and its runbook when the
target is one of them.

The Phase 95 pattern transplants cleanly: a Canonical-bundle MCP
descriptor for MAAS (the only one of the three with a stable read /
write tool surface), substrate-aware guidance for OpenStack and
MicroCloud (the cheaper, larger-leverage path), and detection logic
that fits inside the existing `list_controllers()` and
`_K8S_CLOUDS` machinery.  No parallel abstraction, no Concierge
fork, no second environment story to maintain.
