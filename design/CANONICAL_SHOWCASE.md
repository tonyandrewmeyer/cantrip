# Canonical Products and Technology Fit for Cantrip — Research Findings

> Output of the 2026-04-30 Canonical-showcase sweep.  This is a
> research note, not a design.  It records which Canonical offerings
> were reviewed, how they map onto Cantrip's current surface, and
> which ones are worth turning into roadmap work.

## TL;DR

- **Best next additions:** Launchpad, Snapcraft / Charmcraft
  surfaces, Chisel / chiselled Ubuntu, MAAS, OpenStack /
  MicroCloud, and Ubuntu Pro / Landscape guidance.
- **Already strong showcases:** Juju, charms, Charmcraft,
  Rockcraft, Ops / Pebble / Scenario, Jubilant, COS, local
  inference snaps, LXD, and the Canonical Identity Platform work
  that already landed as Phase 88.
- **Do not roadmap everything Canonical ships.**  Prioritise the
  offerings that either make the agent better at autonomous charm
  work or make the generated charms materially better.

## 1. What I looked at

### 1.1 Internal Cantrip context

These repo files established what Cantrip already showcases and where
new Canonical fit points would land:

| Source | Why it mattered |
|---|---|
| `README.md` | Current product promise, existing showcase list, local inference-snap support. |
| `design/PLAN.md` | States that showcasing the Canonical ecosystem is part of the product goal; records current default integrations and environment story. |
| `design/IDENTITY_PLATFORM.md` | Existing precedent for a first-class Canonical product integration with a research-note-first workflow. |
| `design/MCP_SERVERS.md` | Already names Launchpad, Snapcraft, Charmcraft, and MAAS as valuable MCP surfaces. |
| `docs/src/howto-mcp.md` | Current user-facing MCP configuration and marketplace UX. |
| `docs/src/howto-provider.md` | Positions Ubuntu inference snaps as the Canonical-native local-model path. |

### 1.2 External Canonical / official sources

I checked Canonical's umbrella catalogues first, then product-specific
pages and docs:

- [`canonical.com/projects`](https://canonical.com/projects)
- [`canonical.com/solutions`](https://canonical.com/solutions)
- [`canonical.com/observability`](https://canonical.com/observability)
- [`canonical-identity.readthedocs-hosted.com`](https://canonical-identity.readthedocs-hosted.com/reference/canonical-identity-platform-architecture/)
- [`ubuntu.com/pro`](https://ubuntu.com/pro)
- [`ubuntu.com/openstack`](https://ubuntu.com/openstack)
- [`canonical.com/microcloud`](https://canonical.com/microcloud)
- [`canonical.com/lxd`](https://canonical.com/lxd)
- [`canonical.com/maas`](https://canonical.com/maas)
- [`ubuntu.com/kubeflow`](https://ubuntu.com/kubeflow)
- [`ubuntu.com/landscape`](https://ubuntu.com/landscape)
- [`snapcraft.io`](https://snapcraft.io/)
- [`multipass.run`](https://multipass.run/)
- [`netplan.io`](https://netplan.io/)
- [`cloud-init.io`](https://cloud-init.io/)
- [`microk8s.io`](https://microk8s.io/)
- [`documentation.ubuntu.com/charmcraft/stable/`](https://documentation.ubuntu.com/charmcraft/stable/)
- [`documentation.ubuntu.com/rockcraft/stable/`](https://documentation.ubuntu.com/rockcraft/stable/)
- [`documentation.ubuntu.com/chisel/en/latest/`](https://documentation.ubuntu.com/chisel/en/latest/)
- [`launchpad.net`](https://launchpad.net/)

`canonical.com/identity` currently resolves to a 404, so the Identity
Platform assessment used Canonical's hosted docs and Charmhub topic
pages instead.

## 2. Current Cantrip baseline

Before looking for "more Canonical", it was important to separate the
gaps from the parts Cantrip already does well:

- **Core charm stack already showcased well:** Juju, charms,
  Charmcraft, Rockcraft, Ops, Pebble, Scenario, Jubilant, and COS.
- **Canonical-native local inference is already real:** Cantrip ships
  an `inference-snap` provider and the provider docs explicitly call
  Ubuntu inference snaps the Canonical-native path.
- **Identity is already a live precedent:** Phase 88 gave Cantrip a
  proper Canonical Identity Platform story instead of vague "OIDC with
  something" guidance.
- **There is already an obvious extension seam:** the MCP docs and
  design note explicitly call out Launchpad, Snapcraft, Charmcraft,
  and MAAS as good surfaces.

This means the best follow-on work is **not** "find anything with a
Canonical logo".  It is "find Canonical products that slot naturally
into Cantrip's existing workflows".

## 3. Evaluation criteria

Each offering was scored informally against the same questions:

| Criterion | What "good" looks like |
|---|---|
| **Showcase value** | Clearly recognisable Canonical technology, not generic plumbing that happens to ship on Ubuntu. |
| **Functional fit** | Strengthens charm research, generation, deployment, testing, debugging, or operational-readiness work. |
| **Agent leverage** | The agent can *use* it autonomously, not merely mention it in docs. |
| **Implementation shape** | Fits Cantrip's existing patterns: skill, tool, MCP server, environment profile, or audit heuristic. |
| **Scope safety** | Adds charm-building depth without pulling Cantrip into a huge unrelated product line. |

## 4. Survey findings

### 4.1 Already strong showcases

| Offering | Fit analysis | Verdict |
|---|---|---|
| **Juju / charms / Charmhub** | This is the reason Cantrip exists.  No other Canonical product has a stronger product fit. | **Keep central.** |
| **Charmcraft** | Already core to init / pack / publish flows and still one of the clearest Canonical developer stories in the repo. | **Already right.** |
| **Rockcraft** | Already central for OCI-image-backed charms and Path A. | **Already right; extend with Chisel.** |
| **Ops / Pebble / Scenario** | They are the execution model for generated charms and tests. | **Already right.** |
| **Jubilant** | Strong showcase of Canonical's Juju-control tooling in Cantrip's acceptance and integration story. | **Already right.** |
| **Canonical Observability Stack** | Cantrip both wires COS into charms and uses it internally for debugging.  That is exactly the kind of showcase that feels real, not bolted on. | **Excellent showcase; keep mandatory-by-default.** |
| **LXD** | Still the natural machine-charm substrate and already part of the environment story. | **Keep.** |
| **Canonical Identity Platform** | A strong example of "first-class Canonical integration that also solves a real charm need". | **Already landed in Phase 88; use as the model.** |
| **Ubuntu inference snaps** | Canonical-native local-model path, already user-facing and useful. | **Keep and deepen via Snapcraft surfaces.** |

### 4.2 Strong next additions

| Offering | Why it fits Cantrip | Verdict |
|---|---|---|
| **Launchpad** | Helps research, bug triage, merge-proposal lookup, and discovery of unpublished or in-progress charm work.  It complements Charmhub rather than duplicating it. | **High-value next phase.** |
| **Snapcraft / Snap Store** | Cantrip already cares about inference snaps.  Snapcraft can also improve discovery, metadata enrichment, and possibly future packaging/distribution stories. | **High-value next phase.** |
| **Charmcraft surfaced via MCP** | Even with local tools, a dedicated Charmcraft surface is useful because the agent often needs a second opinion on `lint` / `analyse` or a marketplace-discoverable path. | **High-value next phase.** |
| **Chisel / chiselled Ubuntu** | Strong Canonical packaging story and a real technical improvement: smaller, tighter, more secure rocks when the workload fits. | **High-value next phase.** |
| **MAAS** | Strong fit for machine-charm labs and "real substrate" demos.  It is already named in the MCP-server design note. | **High-value, especially for infra and machine charms.** |
| **OpenStack / Sunbeam** | Good target substrate for infrastructure charms and Canonical-cloud demos.  More useful as a deployment profile than as a Cantrip runtime dependency. | **Worth a dedicated substrate phase.** |
| **MicroCloud** | Good compact private-cloud / edge lab story and a cleaner self-contained demo substrate than "bring your own cloud". | **Worth pairing with OpenStack in a substrate phase.** |
| **Ubuntu Pro** | Useful for operational-readiness and production hardening guidance: security maintenance, compliance, and supply-chain posture. | **Good audit/recommendation phase, not a core runtime integration.** |
| **Landscape** | Useful when Cantrip is improving charms for estate-managed Ubuntu fleets.  Strong Canonical story, but it belongs in day-2 guidance more than in the build loop. | **Good audit/recommendation phase.** |

### 4.3 Useful, but lower priority or niche

| Offering | Fit analysis | Verdict |
|---|---|---|
| **Multipass** | Nice onboarding story for macOS/Windows workstations, but less central than Concierge/LXD on Linux and less leverage than Launchpad or Chisel. | **Nice later/onboarding work.** |
| **cloud-init** | Relevant for machine-deployment recipes and demo environments, but secondary to MAAS and OpenStack for Cantrip's core workflows. | **Useful later.** |
| **Netplan** | Only really matters for network-heavy machine charms or troubleshooting guidance. | **Too niche for a near-term phase.** |
| **MicroK8s** | Valid Canonical K8s story, but Cantrip's design currently prefers Canonical K8s rather than MicroK8s for the main path. | **Optional demo path, not the default.** |
| **Charmed Kubeflow** | Excellent *workload to charm or improve*, but less compelling as Cantrip's own infrastructure. | **Use as a showcase workload, not a platform phase.** |
| **Mir** | Mostly relevant for kiosk / display / IoT workloads. | **Not a general Cantrip priority.** |

## 5. Recommendations

### 5.1 What to prioritise

1. **Launchpad, Snapcraft, and Charmcraft surfaces.**
   They give the agent new first-party catalogues and developer
   signals with relatively little architecture risk.
2. **Chisel / chiselled Ubuntu in Rockcraft flows.**
   This is one of the best combinations of "good Canonical showcase"
   and "actual charm-output improvement".
3. **MAAS, OpenStack, and MicroCloud as substrate-aware paths.**
   Strong fit for machine / infrastructure charm stories and demos.
4. **Ubuntu Pro and Landscape in operational-readiness mode.**
   Useful when Cantrip is acting like a production advisor rather
   than just a scaffolder.

### 5.2 What not to prioritise right now

- **Do not open a generic "more Canonical products" phase.**  That
  would encourage shallow integrations with weak product fit.
- **Do not treat every Canonical product as a Cantrip dependency.**
  Some are best as target substrates, some as research/catalogue
  surfaces, and some only as recommendation logic.
- **Do not reopen Identity Platform as a fresh research effort.**
  Phase 88 already solved the important product-shape questions there.

## 6. Proposed roadmap phases

The phase split that best matches the research is:

| Phase | Title | Why this split is right |
|---|---|---|
| **95** | Canonical developer surfaces — Launchpad, Snapcraft, Charmcraft | These are first-party catalogues and tools the agent can use directly during research, provider selection, and packaging. |
| **96** | Chiselled rocks — Chisel-aware Rockcraft output | Packaging deserves its own phase because the heuristic and validation work are distinct from MCP/catalogue work. |
| **97** | Canonical cloud targets — MAAS, OpenStack, MicroCloud | These are substrate choices and environment profiles, not packaging or metadata lookups. |
| **98** | Canonical estate operations — Ubuntu Pro and Landscape | These fit operational-readiness and improvement-mode advice, not core generation flows. |

## 7. Bottom line

The best Canonical showcases for Cantrip are the ones that let the
agent **do more useful autonomous charm work**.  That is why
Launchpad, Snapcraft, Chisel, MAAS, OpenStack, MicroCloud,
Ubuntu Pro, and Landscape rise to the top, while things like
Netplan or Mir do not.

The pattern to preserve is the one already visible in COS and the
Canonical Identity Platform work: pick a Canonical product that
**solves a real charm-builder problem**, then integrate it deeply
enough that the agent can use it rather than merely name-drop it.
