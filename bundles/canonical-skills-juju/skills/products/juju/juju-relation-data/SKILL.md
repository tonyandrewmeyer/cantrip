---
name: juju-relation-data
description: 'Designing and implementing relation data bags for charm integrations.
  WHEN: design a Juju relation data bag, implement provider or requirer side of a
  charm relation, share Juju secrets over relations, design peer relations, write
  data validators.'
license: Apache-2.0
metadata:
  author: Canonical/cantrip
  version: 1.0.0
  summary: Designing and implementing Juju relation databags (app + unit + peer),
    with safe secret sharing over relations.
  tags:
  - juju
  - ops
  - relations
  - data-bag
  - secrets
---

<!--
Generated from Cantrip's source skill at
`src/cantrip/skills/relation-data-design/SKILL.md`
(https://github.com/canonical/cantrip). Do NOT hand-edit —
re-run `make juju-skills-bundle` instead.

Procedure steps may reference cantrip-specific helper tools (for
example `charm_validate`, `quick_pack`, `harness_inventory`).
Substitute the equivalent `charmcraft` / `juju` / standard CLI
invocation when running without cantrip.
-->

# Relation Data Bag Design

Relations are how Juju charms communicate. Each relation has **data bags** — key-value stores that charms read and write to exchange configuration, credentials, and status.

## Key Concepts

### Data Bag Scopes

- **Application data bag** — shared across all units of an application. Only the **leader** can write. Use for configuration that applies to the whole application (e.g., database connection string, endpoint URL).
- **Unit data bag** — per-unit data. Any unit can write to its own bag. Use for unit-specific information (e.g., IP address, readiness state).

### Relation Sides

- **Provider** — the application offering a service (e.g., a database)
- **Requirer** — the application consuming the service (e.g., a web app needing a database)
- **Peer** — relations between units of the same application (for clustering, leader election data)

## Step 1: Define the Relation in Metadata

In `charmcraft.yaml`:

```yaml
provides:
  website:
    interface: http

requires:
  database:
    interface: mysql
    limit: 1

peers:
  cluster:
    interface: myapp-cluster
```

## Step 2: Choose an Interface Library

Prefer existing interface libraries from PyPI or Charmhub. Common interfaces:

| Interface | PyPI Package | Purpose |
|-----------|-------------|---------|
| `mysql` | `ops-lib-mysql` | MySQL database |
| `postgresql` | `ops-lib-pgsql` | PostgreSQL database |
| `ingress` | `traefik-route-k8s` | HTTP ingress |
| `tracing` | `ops-tracing` | Distributed tracing |
| `grafana-dashboard` | — | Grafana dashboards |
| `loki-push-api` | — | Log forwarding |
| `prometheus-scrape` | — | Metrics scraping |

Check PyPI first; fall back to `charmcraft fetch-libs` for Charmhub-only libraries.

## Step 3: Implement a Requires Relation (Consumer Side)

```python
import ops


class MyCharm(ops.CharmBase):
    def __init__(self, framework: ops.Framework):
        super().__init__(framework)
        self.framework.observe(
            self.on.database_relation_changed,
            self._on_database_changed,
        )
        self.framework.observe(
            self.on.database_relation_broken,
            self._on_database_broken,
        )

    def _on_database_changed(self, event: ops.RelationChangedEvent):
        if not event.relation.data.get(event.app):
            return
        data = event.relation.data[event.app]
        host = data.get("host")
        port = data.get("port")
        if not host or not port:
            self.unit.status = ops.WaitingStatus("waiting for database credentials")
            return
        # Configure workload with database connection.
        self.unit.status = ops.ActiveStatus()

    def _on_database_broken(self, event: ops.RelationBrokenEvent):
        # Clean up database configuration.
        self.unit.status = ops.BlockedStatus("database relation removed")
```

## Step 4: Implement a Provides Relation (Provider Side)

```python
def _on_website_relation_joined(self, event: ops.RelationJoinedEvent):
    if not self.unit.is_leader():
        return
    event.relation.data[self.app]["url"] = f"http://{self._get_hostname()}:8080"
    event.relation.data[self.app]["port"] = "8080"
```

## Step 5: Implement Peer Relations

Peer relations are useful for sharing state between units:

```python
def _on_cluster_relation_changed(self, event: ops.RelationChangedEvent):
    # Read data from other units.
    for unit in event.relation.units:
        unit_data = event.relation.data[unit]
        ip = unit_data.get("ip")
        if ip:
            # Add to cluster membership list.
            ...

def _set_unit_address(self):
    # Write this unit's data to the peer relation.
    rel = self.model.get_relation("cluster")
    if rel:
        rel.data[self.unit]["ip"] = str(self.model.get_binding("cluster").network.bind_address)
```

## Design Principles

1. **Application data for shared config, unit data for per-unit info.** Database credentials go in app data (set by leader). Unit IP addresses go in unit data.

2. **Only the leader writes app data.** Always guard with `self.unit.is_leader()` before writing to `event.relation.data[self.app]`.

3. **Validate before using.** Remote data may be incomplete. Always check for required keys before acting on relation data.

4. **Use `relation-changed` for updates.** This event fires whenever the remote side updates its data bags. Handle partial data gracefully — the remote application may set fields incrementally.

5. **Use `relation-broken` for cleanup.** Remove any configuration that depends on the relation.

6. **All values must be strings.** Relation data bags only store `str` → `str` mappings. Serialise complex data with JSON if needed, but prefer flat key-value pairs.

7. **Keep data bags small.** Do not store large blobs. Use relation data for connection parameters and metadata, not bulk data.

8. **Use interface libraries where possible.** They handle serialisation, validation, and versioning of the data format. Writing raw relation data is acceptable for simple custom interfaces.

## Secrets in relation data

When the charm shares a Juju secret over a relation, put only the secret
*identifier* (an opaque string) in the relation databag — never the
secret body. Two rules worth knowing:

- **Secret IDs are opaque.** Do not parse, match by length, or assume
  the `secret://Xid` form. Treat the value as a blob and hand it back to
  the framework (`self.model.get_secret(id=...)`).
- **Secrets over cross-model relations (CMR): only the offering
  application can grant access.** The side of the relation that created
  the secret must call `secret.grant(relation)` — consuming charms cannot
  grant to themselves. When you're writing the charm that owns the
  secret, do the grant in the relation-joined / relation-changed
  handler. When you're writing the consumer, just `get_secret(id=...)`;
  do not attempt to manage the grant from your side.

```python
# Owner (offering) side
def _on_db_relation_changed(self, event):
    if not self.unit.is_leader():
        return
    secret = self.model.get_secret(label="db-password")
    secret.grant(event.relation)
    event.relation.data[self.app]["password-id"] = secret.id

# Consumer side
def _on_db_relation_changed(self, event):
    secret_id = event.relation.data[event.app].get("password-id")
    if not secret_id:
        return
    secret = self.model.get_secret(id=secret_id)
    password = secret.get_content()["password"]
```

## Common Pitfalls

- **Writing app data from a non-leader unit, or reading `event.relation.data[event.app]` without guarding `event.app`.** Both are checked deterministically by `charmlint` — `REL001` flags subscript reads on `event.app` / `event.unit` without an `is None` / `.get()` guard; `REL002` flags writes to `event.relation.data[self.app]` without an `is_leader()` guard. Run `charmlint` to surface these.
- **Forgetting to handle `relation-broken`** — the charm should gracefully degrade when a relation is removed.
- **Putting secret *bodies* in relation data** — share the opaque secret
  ID instead, and grant access via `secret.grant(relation)`.
- **Parsing secret IDs.** They are opaque strings; do not assume the
  `Xid` format or any specific length.
