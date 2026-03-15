---
name: observability
description: Adding COS observability integration and ops-tracing to charms
---

# Observability and COS Integration

Every production charm should integrate with the **Canonical Observability Stack (COS)**. This means traces, metrics, logs, and dashboards — all wired up through standard Juju relations.

## Key Components

| Component | Purpose | Relation Interface |
|-----------|---------|-------------------|
| **ops-tracing** | Distributed tracing from charm code | `tracing` |
| **Prometheus** | Metrics collection | `prometheus-scrape`, `metrics-endpoint` |
| **Loki** | Log aggregation | `loki-push-api`, `logging` |
| **Grafana** | Dashboards | `grafana-dashboard` |
| **Tempo** | Trace storage and querying | `tracing` |
| **Alertmanager** | Alert routing | `alertmanager-dispatch` |

## Step 1: Add ops-tracing

> **Note:** The `charmcraft_init` tool now automatically injects ops-tracing for standard charms (`kubernetes`/`machine` profiles) — it adds the dependency to `requirements.txt`, the tracing relation to `charmcraft.yaml`, and the import/setup call to `src/charm.py`. For PaaS framework profiles, it adds the tracing relation to `charmcraft.yaml` only. If your charm was scaffolded with `charmcraft_init`, you can skip to Step 2.

ops-tracing instruments charm code so every hook execution, relation event, and Pebble interaction produces a trace span.

Install from PyPI:

```toml
[project.dependencies]
ops-tracing = ["ops-tracing"]
```

Add the tracing relation to `charmcraft.yaml`:

```yaml
requires:
  tracing:
    interface: tracing
    limit: 1
```

Integrate in the charm:

```python
import ops
import ops_tracing


class MyCharm(ops.CharmBase):
    def __init__(self, framework: ops.Framework):
        super().__init__(framework)
        ops_tracing.setup(self)
        # ... rest of charm init
```

That single `ops_tracing.setup(self)` call handles everything — it watches for the tracing relation and sends spans to Tempo automatically.

## Step 2: Add Metrics Endpoint

Expose Prometheus metrics from the workload:

```yaml
# charmcraft.yaml
provides:
  metrics-endpoint:
    interface: prometheus_scrape
```

Configure the scrape target in the charm:

```python
from charms.prometheus_k8s.v0.prometheus_scrape import MetricsEndpointProvider


class MyCharm(ops.CharmBase):
    def __init__(self, framework: ops.Framework):
        super().__init__(framework)
        self._metrics = MetricsEndpointProvider(
            self,
            relation_name="metrics-endpoint",
            jobs=[{
                "static_configs": [{"targets": ["*:8080"]}],
                "scrape_interval": "30s",
            }],
        )
```

## Step 3: Add Log Forwarding

Forward workload logs to Loki:

```yaml
# charmcraft.yaml
requires:
  logging:
    interface: loki_push_api
```

```python
from charms.loki_k8s.v1.loki_push_api import LogForwarder


class MyCharm(ops.CharmBase):
    def __init__(self, framework: ops.Framework):
        super().__init__(framework)
        self._log_forwarder = LogForwarder(self, relation_name="logging")
```

## Step 4: Add Grafana Dashboards

Provide a built-in Grafana dashboard:

```yaml
# charmcraft.yaml
provides:
  grafana-dashboard:
    interface: grafana_dashboard
```

```python
from charms.grafana_k8s.v0.grafana_dashboards import GrafanaDashboardProvider


class MyCharm(ops.CharmBase):
    def __init__(self, framework: ops.Framework):
        super().__init__(framework)
        self._grafana = GrafanaDashboardProvider(self)
```

Place dashboard JSON files in `src/grafana_dashboards/`. The library picks them up automatically.

## Step 5: Deploy COS and Relate

```bash
# Deploy COS-lite bundle to a separate model.
juju add-model cos
juju deploy cos-lite --trust

# Cross-model relate.
juju switch dev-model
juju integrate my-charm:tracing cos.tempo:tracing
juju integrate my-charm:metrics-endpoint cos.prometheus:metrics-endpoint
juju integrate my-charm:logging cos.loki:logging
juju integrate my-charm:grafana-dashboard cos.grafana:grafana-dashboard
```

## Step 6: Verify Observability

After deployment, verify:

1. **Traces** — check Tempo for spans from your charm's hook executions
2. **Metrics** — check Prometheus targets to confirm scraping is active
3. **Logs** — check Loki for workload log streams
4. **Dashboards** — open Grafana and find the auto-provisioned dashboard

## Querying for Debugging

Once COS is deployed and related, use the observability tools to investigate charm issues.

### Step-by-step debugging workflow

1. **Start with `juju_debug_log`** — no COS needed:
   ```
   juju_debug_log(unit="my-charm/0", level="ERROR")
   ```

2. **Query traces in Tempo** — see hook execution timelines:
   ```
   tempo_query(service_name="my-charm", cos_model="cos")
   ```

3. **Search for specific errors with TraceQL**:
   ```
   tempo_query(query="{ status = error }", cos_model="cos")
   ```

4. **Fetch a specific trace for details**:
   ```
   tempo_query(trace_id="abc123def456", cos_model="cos")
   ```

5. **Query logs in Loki** — find workload errors:
   ```
   loki_query(query='{juju_application="my-charm"} |= "error"', cos_model="cos")
   ```

6. **Search wider time ranges**:
   ```
   loki_query(query='{juju_application="my-charm"}', hours=24, cos_model="cos")
   ```

### Tips

- `juju_debug_log` works without COS — use it as the first debugging step.
- Tempo traces show the full timeline of a hook execution, including which relation events fired and in what order.
- Loki logs capture workload stdout/stderr — look here for application-level tracebacks.
- Both `tempo_query` and `loki_query` use SSH into the COS units, so the COS model must be accessible.

## Best Practices

1. **Always include ops-tracing.** It has minimal overhead and provides invaluable debugging information. Traces show the full hook execution timeline.

2. **Use cross-model relations for COS.** Keep the observability stack in a separate Juju model from the charm under development. This prevents COS issues from affecting the workload.

3. **Design dashboards early.** Even a simple dashboard showing key metrics and status is valuable. Iterate on it as the charm matures.

4. **Instrument the workload too.** If the workload supports OpenTelemetry or Prometheus metrics natively, expose those alongside charm-level observability.

5. **Fetch libraries from PyPI first.** `ops-tracing` is on PyPI. For Grafana, Loki, and Prometheus libraries, check PyPI; fall back to `charmcraft fetch-libs`.

## Manual Tracing Instrumentation

ops-tracing automatically instruments hook execution, Pebble calls, relation data access,
status changes, secret operations, and charm library calls. Only add manual spans where
ops-tracing has no visibility.

### When to Add Manual Spans

- **Long-running workload operations** — database migrations, backups to object storage,
  cluster joins. Wrap the sequence in a span so traces show duration and failure point.
- **External API calls** — cloud APIs, webhooks, DNS providers. ops-tracing only covers
  the Juju/Pebble boundary, not arbitrary HTTP requests.
- **Decision logic with fallback** — try primary endpoint, fall back to secondary, fall
  back to degraded mode. Span the decision to make the chosen path visible.
- **Deferred event processing** — span deferred handlers separately so traces show the
  gap between deferral and execution.

### When NOT to Add Manual Spans

- Simple event handlers that just call Pebble (already traced)
- Config-changed handlers that update a Pebble layer (already traced)
- Relation-changed handlers that read databag values (already traced)
- Status setting (already traced)
- Any operation completing in under 100ms with no external calls

### Code Example

```python
from opentelemetry import trace

tracer = trace.get_tracer(__name__)


class MyCharm(ops.CharmBase):
    def _run_backup(self, event):
        """Run a database backup — manual span for visibility."""
        with tracer.start_as_current_span("run-backup") as span:
            span.set_attribute("backup.target", self._backup_path)
            self._dump_database()
            span.set_attribute("backup.size_bytes", self._get_backup_size())
            self._upload_to_s3()
            span.add_event("backup-complete")
```

The span appears as a child of the action hook span in Tempo, showing exactly how long
the backup took and which step failed if something goes wrong.

## Security Event Logging (SEC0045)

Charms wrapping security-relevant workloads should emit structured security event logs
following the OWASP Logging Vocabulary and Canonical's SEC0045 standard.

### When to Add Security Event Logging

Add security events when the workload involves:
- Authentication or authorisation (login services, LDAP, OAuth providers)
- Secret or credential management (vaults, certificate authorities, key stores)
- Network access control (firewalls, proxies, ingress controllers)
- Data access with audit requirements (databases, object stores, file servers)
- System administration (backup tools, monitoring agents, config management)

Skip security event logging for workloads with no meaningful security surface.

### Event Format

Events follow the OWASP schema — JSON with these required fields:

```json
{
    "datetime": "2025-01-15T12:30:00+00:00",
    "appid": "my-charm.juju",
    "type": "security",
    "event": "authn_login_fail:admin",
    "level": "WARN",
    "description": "Failed login attempt for user admin"
}
```

### Helper Module Pattern

Generate a `src/log_security.py` helper:

```python
"""Structured security event logging following SEC0045/OWASP."""

import datetime
import json
import logging

logger = logging.getLogger("security")


def log_security_event(
    appid: str,
    event: str,
    level: str,
    description: str,
) -> None:
    """Emit a structured security event at Juju TRACE level."""
    record = {
        "datetime": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "appid": appid,
        "type": "security",
        "event": event,
        "level": level,
        "description": description,
    }
    # Security events are structured data for collectors, not operator messages.
    logger.debug(json.dumps(record))
```

### Common Event Types

| Category | Event | Level | When |
|----------|-------|-------|------|
| AUTHN | `authn_login_success:user` | INFO | Successful authentication |
| AUTHN | `authn_login_fail:user` | WARN | Failed authentication attempt |
| AUTHN | `authn_login_lock:user` | WARN | Account locked after failures |
| AUTHN | `authn_password_change:user` | INFO | Password changed |
| AUTHN | `authn_token_created:service` | INFO | Token created |
| AUTHN | `authn_token_revoked:service,id` | INFO | Token revoked |
| AUTHN | `authn_token_reuse:service,id` | CRITICAL | Revoked token reuse attempt |
| AUTHZ | `authz_fail:user,resource` | CRITICAL | Unauthorised access attempt |
| AUTHZ | `authz_admin:user,action` | WARN | Administrative action |
| SYS | `sys_startup:user` | WARN | System started |
| SYS | `sys_shutdown:user` | WARN | System stopped |
| SYS | `sys_restart:user` | WARN | System restarted |
| SYS | `sys_crash:reason` | WARN | System crashed |
| SYS | `sys_monitor_disabled:user,tool` | WARN | Monitoring disabled |
| USER | `user_created:admin,user,privs` | WARN | User account created |
| USER | `user_updated:admin,user,privs` | WARN | User account modified |

### Querying Security Events in Loki

Filter for security events using LogQL:

```
loki_query(query='{juju_application="my-charm"} | json | type="security"', cos_model="cos")
```

Filter by event category:

```
loki_query(query='{juju_application="my-charm"} | json | type="security" | event=~"authn_.*"', cos_model="cos")
```

### Critical Rule

**Never log sensitive data** — no credentials, tokens, passwords, or secret content in
event descriptions. Log *what happened* (e.g. "Secret rotated for relation endpoint
'database'"), not *what the secret contains*.

## Common Pitfalls

- **Forgetting `--trust`** when deploying COS components that need cluster-wide access.
- **Not adding the relation endpoints to `charmcraft.yaml`** — the charm will not see the relations if they are not declared in metadata.
- **Large dashboards in the charm** — keep dashboard JSON reasonable in size. Grafana rejects very large dashboard definitions sent over relation data.
