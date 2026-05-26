---
name: preset-bundles
description: Known-good Juju bundle shapes (COS Lite, 12-Factor + COS, Identity Platform, Charmed Kubeflow) — canonical app lists and relation edges
---

# Preset Bundle Shapes

Use this skill when you are **composing relations** for a multi-charm
deployment, or **diagnosing one that already exists**, and the shape is
one the ecosystem already agrees on. Instead of re-deriving "which apps,
which relations, which interface names" from web docs every turn, pull
the canonical layout from Cantrip's preset catalogue.

This is *knowledge*, not a deployment recipe — it tells you the target
shape, not the steps. To actually deploy a multi-charm stack, issue
`juju_deploy` + `juju_relate` calls (see the `bundle` skill for why not
a `bundle.yaml`). To turn a deployment into reusable infrastructure, see
the `terraform` skill.

## What's in the catalogue

`cantrip.agent.presets.CATALOGUE` records, for each known shape: the
apps and the semantic layer each belongs to, and every relation edge
with its interface name and a one-line description of what flows across
it. Current entries:

| Slug | Shape |
| --- | --- |
| `cos-lite` | Canonical's observability stack — Prometheus, Loki, Alertmanager, Grafana, Catalogue behind one Traefik. What a Cantrip-built charm relates to (usually cross-model) for observability. |
| `twelve-factor-cos` | A paas-charm 12-Factor app in production: the app charm + PostgreSQL + Traefik in its own model, plus the metrics / logs / dashboards / tracing endpoints the framework exposes (typically consumed cross-model from COS Lite). Add Redis when the framework needs a cache or Celery broker. |
| `identity-platform` | The `canonical-identity-platform` bundle behind the bundle-based-hybrid login default — Hydra (OAuth2/OIDC) + Kratos (identity/sessions) + login-UI + PostgreSQL behind public and admin Traefiks, with self-signed-certificates. A relying-party charm relates to Hydra over `oauth`. |
| `charmed-kubeflow` | The auth-and-routing core of Charmed Kubeflow — Istio pilot + ingress gateway fronting the Kubeflow dashboard, with Dex + the OIDC gatekeeper enforcing login at the mesh edge and the profiles controller backing per-user namespaces. Orientation map, not the deployable bundle. |

## How to use it

- **In chat**, type `@preset` to see the index, or `@preset cos-lite`
  (etc.) to expand one shape inline — apps grouped by layer, then every
  edge with its interface name and prose. Reach for this *before*
  guessing relation endpoints for a well-known stack.
- **When composing relations**, use the catalogue's edge list as the
  checklist: each `provider → requirer · interface` line is one
  `juju_relate` call. Cross-reference the per-charm skill
  (`observability`, `twelve-factor`, `identity-platform`,
  `infrastructure-charm`) for the *requirer*-side library wiring; this
  skill gives you the *topology*.
- **When diagnosing**, compare the live `juju_status` integration list
  against the preset's edges — a missing edge (e.g. no
  `alertmanager_dispatch` between Prometheus and Alertmanager) is a
  concrete "you forgot to relate X and Y" finding.

## Substrate refinements (Canonical clouds)

When the active Juju controller targets a Canonical cloud, the preset's
shape still holds — but the *implementation choices* under the edges
shift. The system prompt's `Substrate` block (Phase 97.3) surfaces the
relevant flag; mirror its guidance in your DESIGN.md choices and your
`juju_deploy` calls.

### OpenStack / Sunbeam

When `active cloud: openstack` (or `sunbeam`) is in the substrate block:

- **Persistent storage**: prefer the **cinder-csi** storage class for
  stateful workloads rather than the default ephemeral storage. The
  preset's relation list is unchanged; what changes is the `storage:`
  entry in `charmcraft.yaml` and the storage class consumed at deploy
  time.
- **Ingress**: prefer **neutron-api**-backed ingress (the OpenStack
  load-balancer-as-a-service surface) over a generic NodePort. For the
  `twelve-factor-cos` preset's Traefik edge this means a neutron-api
  relation in front of the Traefik unit rather than a node-port
  Service.
- **Resilience acceptance**: the autodeploy hook adds an OpenStack
  acceptance task that exercises AZ-loss + volume-detach recovery —
  align the charm's `pebble` lifecycle and storage handling so those
  scenarios survive without manual intervention.

### MicroCloud

When `MicroCloud detected` is in the substrate block:

- **Stateful workloads**: recommend **MicroCeph** as the storage
  backend. The relation shape is the same as any other Ceph-aware
  storage relation; what changes is the cluster the charm consumes —
  point storage requirers at the MicroCeph deployment that ships
  alongside the LXD substrate.
- **K8s components on the same host**: MicroCloud installs a parallel
  **MicroK8s sibling cluster** on the same machine. Cantrip's existing
  cross-controller COS path (`_find_k8s_controller`) picks it up
  automatically — surface this in DESIGN.md so a reader doesn't think
  K8s components need a remote controller.

## Scope

- Not a `bundle.yaml` generator and not a deployment runbook — it
  prescribes no steps and emits no YAML.
- Not exhaustive: `charmed-kubeflow` is a deliberate subset (the full
  bundle is ~30 charms), and the COS / 12-Factor entries list the
  primary edges, not every self-monitoring relation.
- Endpoint names are intentionally omitted from the edge records —
  they drift between charm revisions; the interface name and the prose
  are the stable parts. When you need the exact endpoint, read the
  charm's metadata (`@charm <name>`).

## References

- `@preset` context provider — the inline surface for this catalogue.
- `cantrip.agent.presets` — the catalogue source, also consumed by the
  F8 integration-graph screen for layer grouping and edge prose.
- `bundle` skill — why new deployments use `juju_deploy` + `juju_relate`
  rather than a bundle file.
- `observability`, `twelve-factor`, `identity-platform`,
  `infrastructure-charm` skills — requirer-side wiring for the charms
  these presets reference.
