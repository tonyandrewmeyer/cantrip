---
name: bundle
description: Reading, modifying, and deploying existing Juju bundles (bundles are deprecated — do not create new ones)
---

# Juju Bundles

Use this skill when the user has an **existing** Juju bundle they want
to deploy, modify, or understand. **Do not write new bundles** — they
are deprecated. For new multi-charm deployments, issue a series of
`juju_deploy` + `juju_relate` calls instead. That's what this skill
exists to help you migrate *away* from.

## Why bundles are deprecated

Juju bundles are YAML documents that deploy multiple applications and
their relations in a single command. The bundle format still works and
Canonical still ships widely-used bundles (`cos-lite`, `kubeflow`,
`canonical-openstack`), but **Juju no longer accepts new bundles on
Charmhub**, and the bundle format is frozen — new Juju features
(Juju secrets, newer base syntax, Terraform modules) land in the core
`juju` CLI and in Terraform modules, not in bundles.

Treat bundles like `apt-get source` — a fine way to consume an
existing recipe, but not the medium you write new ones in.

## When to load

- The user says "deploy cos-lite", "deploy this bundle", or hands you
  a `bundle.yaml`.
- The user wants to change an existing deployment that was originally
  deployed via a bundle.
- You need to read a bundle to understand how a multi-charm deployment
  is shaped (e.g. the user has "an observability stack" and you need
  to see which charms and relations it contains).

If the user wants a **new** multi-charm deployment, skip this skill:
plan a sequence of `juju_deploy` + `juju_relate` tool calls instead.

## Bundle structure

A minimal bundle (`bundle.yaml`):

```yaml
bundle: kubernetes  # or "machine" for LXD/MAAS
applications:
  prometheus:
    charm: prometheus-k8s
    channel: latest/stable
    scale: 1
    trust: true
  grafana:
    charm: grafana-k8s
    channel: latest/stable
    scale: 1
    trust: true
    options:
      admin_password: "changeme"
relations:
  - - prometheus:grafana-source
    - grafana:grafana-source
```

Key fields inside each application:

| Field | Purpose |
| --- | --- |
| `charm` | Charmhub charm name, a Git reference, or a local `.charm` path |
| `channel` | Charmhub channel (e.g. `latest/stable`, `2/edge`) |
| `scale` / `num_units` | K8s uses `scale`; machine uses `num_units` |
| `trust` | Grant `--trust` on deploy (cluster-wide K8s privileges) |
| `options` | Config options as a plain map |
| `resources` | Named resources, typically OCI images |
| `constraints` | Machine/pod constraints (cores, memory, tags) |
| `expose` | Boolean — equivalent to `juju expose <app>` |
| `storage` | Named storage pools and sizes |

`relations:` is a list of pairs — each pair is a two-element list of
`app:endpoint` strings.

## Deploying a bundle

Use the `bundle_deploy` tool. The minimum invocation is:

```
bundle_deploy(path="./bundle.yaml")
```

With overlays:

```
bundle_deploy(
    path="./cos-lite/bundle.yaml",
    overlays=["./cos-lite/overlays/offers-overlay.yaml",
              "./cos-lite/overlays/storage-small-overlay.yaml"],
    trust=True,
)
```

`bundle_deploy` wraps Jubilant's `Juju.deploy()` with a bundle path —
which in turn shells out to `juju deploy ./bundle.yaml --overlay ...
[--trust]`. The tool resolves relative paths from the current working
directory and fails early if the bundle or any overlay is missing, so
typos are caught before anything deploys.

After the tool returns, use `juju_wait` to block until every
application reaches `active` (or the expected blocked state — some
bundles block waiting for integrations into applications not in the
bundle).

## Overlays — the way to modify existing bundles

An **overlay** is itself a bundle, merged onto the base. Overlays are
the right tool when you want to keep the upstream bundle as-is and
layer your changes on top — for example, the canonical cos-lite
bundle ships with built-in overlays for cross-model offers, bigger
storage, and edge-channel charms.

### Overlay precedence

- Scalars (`channel`, `scale`, `options.*` values) in an overlay
  **replace** the base. To revert to the upstream value, omit the key.
- `relations` entries from the overlay are **added** to the base's
  list — they don't replace it.
- `applications.<name>: null` **removes** that application from the
  base. `relations` entries touching the removed application are
  dropped silently.
- Multiple overlays are applied in order; the last one wins for
  conflicting scalar values.

### Worked overlay examples

Pin the Grafana channel and bump its scale:

```yaml
applications:
  grafana:
    channel: 1/stable
    scale: 3
```

Remove an application the upstream bundle deploys but you don't want:

```yaml
applications:
  alertmanager: null
relations: []
```

Swap an internal relation for a cross-model offer (pattern used by the
cos-lite offers overlay):

```yaml
applications:
  prometheus:
    offers:
      prometheus-receive-remote-write:
        endpoints: [receive-remote-write]
```

### When overlay-vs-rewrite is ambiguous

If your overlay ends up rewriting most fields in an application, stop
and migrate that application out of the bundle entirely — deploy it
with `juju_deploy` next to the (slimmer) bundle instead. Bundles are
read-only knowledge at this point; the long-term direction is to have
no bundle in the picture at all.

## Reading a bundle the user hands you

Walk the file in this order so you build the same mental model as the
person who wrote it:

1. **`bundle:`** — is this Kubernetes or machine? That determines the
   substrate for every application unless overridden per-application.
2. **`applications:`** — list them with `charm` / `channel` / `scale`
   / `trust`. This is the deployment surface.
3. **`resources:`** under each application — OCI images the charm
   needs. You may need to pre-push these with `registry_search` /
   `skopeo_registry_push` before deploy.
4. **`relations:`** — the integration graph. Sketch it mentally as a
   list of "A provides X to B" edges; that's what the charm author is
   asking Juju to wire up.
5. **`options:`** — per-application config. Anything that looks like a
   secret value here is a smell; Juju secrets aren't expressible in
   bundle YAML, so sensitive values in `options:` are always in
   plaintext. Flag these to the user during audit.

If the user asks "what does this bundle do?", your summary should be
the application list, the integration graph, and any trust/privilege
requests — in that order.

## Migrating a bundle-based deployment to individual juju commands

When the user says "I want to stop using this bundle", the target is a
series of shell-level `juju deploy` / `juju relate` commands (issued
via Cantrip's `juju_deploy` / `juju_relate` tools). The migration is
mechanical:

1. For each `applications.<name>` block:

   ```
   juju_deploy(
       charm="<charm>",
       app_name="<name>",
       channel="<channel>",
       num_units=<scale>,
       trust=<trust>,
       config=<options dict>,
       resources=<resources dict>,
   )
   ```

2. For each `relations` pair, one call:

   ```
   juju_relate(app1="prometheus:grafana-source", app2="grafana:grafana-source")
   ```

3. For each `offers:` block, `juju_offer(...)` followed by
   `juju_consume(...)` in the consuming model.

4. Expose / trust / storage options fall through to their matching
   tool arguments or a follow-up `juju_trust` / `juju_config` /
   `juju_add_storage` call.

Commit the new set of commands (shell script or Terraform module) in
place of the bundle. See also the `terraform` skill for turning a
migrated deployment into a reusable Terraform module — Terraform is
the officially recommended replacement for bundle-based orchestration.

## Do not create new bundles

If the user asks you to "generate a bundle" or "write a bundle.yaml",
push back: explain that bundles are deprecated and propose either

- a set of `juju_deploy` + `juju_relate` calls (fast, imperative, what
  the user typically wants when they say "deploy my stack"), or
- a Terraform module using the `juju` provider (the long-term
  replacement — load the `terraform` skill for the module shape).

Only write a bundle if the user explicitly insists after hearing this,
and then record in the commit message that this was user-directed.

## References

- Canonical: [Juju bundle specification](https://documentation.ubuntu.com/juju/latest/user/reference/bundle/)
- `terraform` skill — the officially recommended replacement for
  bundles in new deployments.
- `custom-charm`, `twelve-factor`, `infrastructure-charm` skills —
  per-charm authoring guidance for the charms a bundle references.
