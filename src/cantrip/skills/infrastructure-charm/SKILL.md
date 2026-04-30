---
name: infrastructure-charm
description: Workflow for charming infrastructure software (databases, caches, message brokers, proxies, monitoring)
---

# Infrastructure Charm Workflow

This skill covers building Juju charms for **infrastructure software** — databases, caches, message brokers, proxies, and monitoring systems. These workloads have complex operational requirements (replication, failover, backup/restore, clustering) that go beyond simple application charming.

## When to Use This Path

Use this path (Path C) when the workload is:
- A **database** (PostgreSQL, MySQL, MongoDB, Redis, Cassandra, etc.)
- A **cache** (Redis, Memcached, Varnish, etc.)
- A **message broker** (Kafka, RabbitMQ, NATS, Pulsar, etc.)
- A **proxy or load balancer** (HAProxy, Nginx, Envoy, etc.)
- A **monitoring system** (Prometheus, Grafana, Alertmanager, etc.)
- Any software where **operational patterns** (primary/replica, leader election, clustering) are the core concern

Do **not** use this path for:
- Flask, Django, FastAPI, Go, Express, Spring Boot → use the `twelve-factor` skill
- Custom applications without complex operational patterns → use the `custom-charm` skill

## Decision Workflow

Infrastructure charming always starts with research. Follow this sequence:

### 1. Search Charmhub

Use `charmhub_search` to check whether a charm already exists:

```
charmhub_search(query="postgresql", category="databases")
```

### 2. Evaluate Existing Charms

If results are found, use `charmhub_info` to inspect the best candidate:

```
charmhub_info(name="postgresql-k8s")
```

Review the relations, config options, storage, and containers. Check whether the charm covers the user's requirements.

### 3. Decide: Use, Fork/Extend, or Build New

| Situation | Action |
|-----------|--------|
| Existing charm meets all requirements | **Use it** — deploy directly with `juju_deploy` |
| Existing charm is close but needs changes | **Fork/extend** — clone the source, modify, repackage |
| No suitable charm exists | **Build new** — scaffold from scratch using this skill |
| User explicitly wants a new charm | **Build new** — even if one exists |

Present the decision to the user with reasoning and wait for confirmation.

### 4. Find the Upstream OCI Image (K8s Charms)

When building a new K8s infrastructure charm, search Docker Hub for the upstream image:

1. `registry_search(query="<workload>")` — find the official or most-used image
2. `registry_image_info(image="<name>")` — check tags, architectures, and freshness
3. Pick a specific version tag (not `latest`) and confirm with the user

This image becomes the OCI resource in `charmcraft.yaml`.

## Research Mode

Before building, deeply research the workload. This is even more important for infrastructure software than for applications because operational patterns are complex and getting them wrong is costly.

### Steps

1. **Clone the upstream source** — `git_clone` with `depth: 1` into `.source/`
2. **Read documentation** — use `web_fetch` for the project's website and deployment docs
3. **Identify the architecture** — is it single-node, primary/replica, clustered? What protocols does it use for replication?
4. **Map operational concerns** — backup/restore, scaling, upgrades, TLS, authentication
5. **Write `WORKLOAD.md`** — summarise findings at the charm root

### WORKLOAD.md for Infrastructure

Include these extra sections beyond the standard format:

```markdown
## Architecture
Single-node / primary-replica / multi-primary / clustered. Replication protocol.

## Operational Patterns
- Failover: automatic or manual? How is the new primary elected?
- Backup: what tools? Snapshots, WAL archiving, logical dumps?
- Scaling: horizontal (add replicas) or vertical (resize)?
- Upgrades: rolling or stop-the-world?

## Client Protocol
Wire protocol, default port, TLS support.

## Observability
Built-in metrics endpoint? What format (Prometheus, StatsD)?
```

## Operational Pattern Templates

Use these patterns as starting points when implementing infrastructure charms.

### Primary/Replica

The leader unit acts as primary; non-leader units are replicas.

```python
def _on_leader_elected(self, event: ops.LeaderElectedEvent) -> None:
    """This unit became the primary."""
    self._configure_as_primary()
    # Share connection details with replicas via peer relation.
    if self.model.get_relation("replication"):
        self.model.get_relation("replication").data[self.app]["primary"] = self._unit_address()
    self.unit.status = ops.ActiveStatus("primary")

def _on_peer_relation_changed(self, event: ops.RelationChangedEvent) -> None:
    """Replica reacts to primary election or config changes."""
    primary = event.relation.data[self.app].get("primary")
    if not primary:
        self.unit.status = ops.WaitingStatus("Waiting for primary")
        return
    if not self.unit.is_leader():
        self._configure_as_replica(primary)
        self.unit.status = ops.ActiveStatus("replica")
```

### Leader Election and Peer Data

Use the peer relation's app data bag for cluster-wide state. Only the leader can write to it.

```python
def _on_peer_relation_joined(self, event: ops.RelationJoinedEvent) -> None:
    """A new unit joined the cluster."""
    if self.unit.is_leader():
        # Share cluster configuration with the new member.
        event.relation.data[self.app]["cluster-key"] = self._generate_cluster_key()

def _unit_address(self) -> str:
    """Return this unit's address for peer communication."""
    binding = self.model.get_binding("replication")
    return str(binding.network.ingress_address)
```

### Backup and Restore Actions

Expose backup/restore as Juju actions:

```yaml
# actions.yaml / charmcraft.yaml actions section
actions:
  create-backup:
    description: Create a backup of the database.
    params:
      destination:
        type: string
        description: S3 URI or local path for the backup.
  restore-backup:
    description: Restore from a backup.
    params:
      source:
        type: string
        description: S3 URI or local path of the backup to restore.
```

```python
def _on_create_backup_action(self, event: ops.ActionEvent) -> None:
    """Run a backup and report the result."""
    destination = event.params.get("destination", "/backups/latest")
    self.unit.status = ops.MaintenanceStatus("Creating backup")
    try:
        self._run_backup(destination)
        event.set_results({"status": "success", "path": destination})
    except subprocess.CalledProcessError as exc:
        event.fail(f"Backup failed: {exc}")
    finally:
        self.unit.status = ops.ActiveStatus()
```

### Clustering / Scale-Out

Handle units joining and departing the cluster:

```python
def _on_peer_relation_joined(self, event: ops.RelationJoinedEvent) -> None:
    """Add the new unit to the cluster membership."""
    if self.unit.is_leader():
        members = self._get_cluster_members(event.relation)
        members.append(event.relation.data[event.unit].get("address", ""))
        event.relation.data[self.app]["members"] = json.dumps(members)

def _on_peer_relation_departed(self, event: ops.RelationDepartedEvent) -> None:
    """Remove the departing unit from the cluster."""
    if self.unit.is_leader():
        members = self._get_cluster_members(event.relation)
        departing = event.relation.data[event.departing_unit].get("address", "")
        members = [m for m in members if m != departing]
        event.relation.data[self.app]["members"] = json.dumps(members)
```

### Failover

Detect primary failure and promote a replica:

```python
def _on_leader_elected(self, event: ops.LeaderElectedEvent) -> None:
    """Handle leader election — may indicate failover."""
    if self._was_replica():
        self._promote_to_primary()
        self.unit.status = ops.ActiveStatus("primary (promoted)")
    else:
        self._configure_as_primary()
        self.unit.status = ops.ActiveStatus("primary")
```

## Fork/Extend Workflow

When an existing Charmhub charm is close but needs modifications:

1. **Find the source** — use `web_fetch` on the charm's Charmhub page to find the source repository
2. **Clone it** — `git_clone` with `depth: 1` into the charm directory
3. **Identify changes needed** — read the charm code, understand the architecture
4. **Make targeted modifications** — edit `src/charm.py`, `charmcraft.yaml`, tests
5. **Pack and deploy** — prefer `quick_pack` (falls back to `charmcraft_pack` if the forked charm uses a non-uv plugin or has override-build steps) → `juju_deploy`
6. **Test** — run existing tests if present, add new tests for modifications

## Scaffolding Guidance

For new infrastructure charms, scaffold with `charmcraft_init` and customise heavily.

### charmcraft.yaml Additions

Infrastructure charms typically need:

```yaml
# Peer relation for cluster coordination.
peers:
  replication:
    interface: <workload>_peers

# Client relation (the interface others use to connect).
provides:
  database:
    interface: <protocol>_client

# Common infrastructure relations.
requires:
  tracing:
    interface: tracing
    limit: 1
  certificates:
    interface: tls-certificates
    limit: 1
  s3-credentials:
    interface: s3
    limit: 1
  # For service-to-service auth (e.g. talking to a downstream API
  # behind Hydra), load the `identity-platform` skill and add an
  # `oauth-cli` requirer here.

# Persistent storage for data.
storage:
  data:
    type: filesystem
    minimum-size: 10G
    location: /var/lib/<workload>

# Actions for operational tasks.
actions:
  create-backup:
    description: Create a backup.
  restore-backup:
    description: Restore from a backup.
  get-password:
    description: Retrieve the admin password.
```

### Common Relations Table

| Relation | Interface | Purpose |
|----------|-----------|---------|
| database | `postgresql_client` / `mysql_client` / `mongodb_client` | Client access |
| replication | `<workload>_peers` | Peer coordination |
| certificates | `tls-certificates` | TLS encryption |
| s3-credentials | `s3` | Backup storage |
| tracing | `tracing` | Distributed tracing (ops-tracing) |
| metrics-endpoint | `prometheus_scrape` | Prometheus metrics |
| grafana-dashboard | `grafana_dashboard` | Dashboard provisioning |
| logging | `loki_push_api` | Log forwarding |

## Testing Notes

Infrastructure charms need tests for operational scenarios that simpler charms do not:

### Unit Tests (Scenario)

- **leader-elected** → unit configures as primary, peer data updated
- **peer-relation-changed** → replica picks up primary address, configures replication
- **storage-attached** → data directory configured correctly
- **config-changed** → workload reconfigured, service restarted
- **scale-up** — new unit joins peer relation, membership updated
- **scale-down** — departing unit removed from membership
- **actions** — backup/restore actions produce correct results
- **relation-joined** for client relations — credentials generated, shared via relation data

### Integration Tests (Jubilant)

- Deploy single unit → ActiveStatus
- Scale to 3 units → all active, replication working
- Relate to client charm → credentials available
- Relate to TLS → encrypted connections
- Run backup action → success
- Remove leader → new leader elected, cluster recovers
- Config change → applied across cluster

## Common Pitfalls

1. **Writing to app data from a non-leader unit** — only the leader can write to `relation.data[self.app]`. Non-leader units write to `relation.data[self.unit]`.

2. **Not handling departing units** — when a unit departs, clean up cluster membership and rebalance if needed.

3. **Blocking hooks with long operations** — database initialisation, backup, and restore can take minutes. Use actions for long-running operations and set `MaintenanceStatus` during the work.

4. **Ignoring storage events** — `storage-attached` fires before `install` on first deploy. Make sure your install handler does not assume storage is already configured.

5. **Hardcoding ports** — make the listening port a config option so operators can customise it.

6. **Missing TLS support** — infrastructure charms should support TLS via the `tls-certificates` relation. Do not skip this.

## Troubleshooting

| Symptom | Likely Cause | Fix |
|---------|-------------|-----|
| Replicas stuck in `waiting` | Primary address not shared via peer relation | Check leader-elected handler writes to app data |
| Data loss after leader change | Replication not configured | Verify replicas are streaming from primary |
| Backup action fails | Missing S3 credentials or wrong path | Check s3-credentials relation and action params |
| Cluster split-brain | No fencing mechanism | Implement STONITH or use Juju leader as tiebreaker |
| Slow failover | Manual promotion required | Automate promotion in leader-elected handler |
| Client cannot connect after TLS | Client charm using wrong CA | Verify TLS relation data includes the CA certificate |
