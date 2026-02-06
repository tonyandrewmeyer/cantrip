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

## Best Practices

1. **Always include ops-tracing.** It has minimal overhead and provides invaluable debugging information. Traces show the full hook execution timeline.

2. **Use cross-model relations for COS.** Keep the observability stack in a separate Juju model from the charm under development. This prevents COS issues from affecting the workload.

3. **Design dashboards early.** Even a simple dashboard showing key metrics and status is valuable. Iterate on it as the charm matures.

4. **Instrument the workload too.** If the workload supports OpenTelemetry or Prometheus metrics natively, expose those alongside charm-level observability.

5. **Fetch libraries from PyPI first.** `ops-tracing` is on PyPI. For Grafana, Loki, and Prometheus libraries, check PyPI; fall back to `charmcraft fetch-libs`.

## Common Pitfalls

- **Forgetting `--trust`** when deploying COS components that need cluster-wide access.
- **Not adding the relation endpoints to `charmcraft.yaml`** — the charm will not see the relations if they are not declared in metadata.
- **Large dashboards in the charm** — keep dashboard JSON reasonable in size. Grafana rejects very large dashboard definitions sent over relation data.
