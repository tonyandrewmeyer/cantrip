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
| **Sloth** | SLO management — generates burn-rate alerts | `slos` |
| **Catalogue** | Landing-page registration | `catalogue` |

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
        self._tracing = ops_tracing.Tracing(self, "tracing")
        # ... rest of charm init
```

That single `Tracing(self, "tracing")` constructor handles everything — it watches for the named tracing relation and sends spans to Tempo automatically. The relation name passed to `Tracing` must match the `tracing:` entry under `requires:` in `charmcraft.yaml`. Do **not** use the legacy `ops_tracing.setup(self)` shorthand — it has been removed from ops-tracing and produces an `AttributeError` at charm import.

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
            jobs=[
                {
                    "static_configs": [{"targets": ["*:8080"]}],
                    "scrape_interval": "30s",
                }
            ],
        )
```

### Alert rules ride along the metrics-endpoint relation

`MetricsEndpointProvider` looks for alert-rule YAML files under
`src/prometheus_alert_rules/` (or whatever path you pass as
`alert_rules_path=`) and forwards them to Prometheus over the same
relation. The charm doesn't need a separate Alertmanager relation —
Prometheus evaluates the rules and dispatches firing alerts to
Alertmanager via the COS bundle's existing wiring.

Drop a small rule file:

```yaml
# src/prometheus_alert_rules/charm_health.yaml
groups:
  - name: charm_health
    rules:
      - alert: HighWorkloadErrorRate
        expr: rate(my_charm_errors_total[5m]) > 0.1
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: Workload error rate is high on {{ $labels.juju_unit }}
          description: |
            More than 10% of requests are erroring on
            {{ $labels.juju_application }}/{{ $labels.juju_unit }} over
            the last 5 minutes.
      - alert: HookExecutionSlow
        expr: histogram_quantile(0.95, rate(juju_hook_duration_seconds_bucket[10m])) > 30
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: p95 hook duration exceeds 30s on {{ $labels.juju_unit }}
```

The YAML is the standard Prometheus alert-rule format — anything
the operator runs locally with `promtool check rules` will work
unchanged. `juju_application`, `juju_unit`, `juju_model`, and
`juju_charm` labels are auto-injected by the COS topology
relabelling, so dashboards and Alertmanager routes can group
alerts by charm without explicit config.

For a Pebble-forwarded workload metric, swap the `expr` for the
metric the workload exposes — the labels work the same way.

If `alert_rules_path` is omitted, `src/prometheus_alert_rules/`
is the default and `MetricsEndpointProvider` discovers anything
matching `*.yaml` / `*.yml` / `*.rules` underneath.

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

### Loki labels in Grafana queries

When a dashboard panel queries Pebble-forwarded workload logs, use the
`charm` label (not `juju_charm`):

```jsonc
// Good — Pebble's log-forwarder sets `charm`.
{ "expr": "{charm=\"my-charm\"} |= ``" }

// Wrong — `juju_charm` is set by the Juju agent for hook logs, not by
// Pebble's workload log forwarding. A dashboard using this filter will
// look empty even when logs are arriving.
{ "expr": "{juju_charm=\"my-charm\"} |= ``" }
```

`juju_application`, `juju_unit`, `juju_model`, and friends are still set
on hook/agent logs and remain the right filter for those.

## Step 5: Deploy COS and Relate

### Single controller (K8s)

```bash
# Deploy COS-lite bundle to a separate model on the same controller.
juju add-model cos
juju deploy cos-lite --trust

# Cross-model relate.
juju switch dev-model
juju integrate my-charm:tracing cos.tempo:tracing
juju integrate my-charm:metrics-endpoint cos.prometheus:metrics-endpoint
juju integrate my-charm:logging cos.loki:logging
juju integrate my-charm:grafana-dashboard cos.grafana:grafana-dashboard
```

### Multi-controller (LXD dev + K8s COS)

When the dev controller is LXD (e.g. `concierge -p dev`), COS must run on the
K8s controller. Preflight handles this automatically, but if doing it manually:

```bash
# Create COS model on the K8s controller.
juju add-model cos -c concierge-k8s
juju deploy cos-lite --trust --model cos

# Create offers for COS endpoints.
juju offer --model cos grafana-k8s:grafana-dashboard
juju offer --model cos prometheus-k8s:receive-remote-write
juju offer --model cos loki-k8s:logging
juju offer --model cos tempo-k8s:tracing

# Consume offers in the dev model.
juju switch dev-model
juju consume cos.grafana-k8s
juju consume cos.prometheus-k8s
juju consume cos.loki-k8s
juju consume cos.tempo-k8s

# For machine charms, deploy grafana-agent (snap-based) locally.
juju deploy grafana-agent
juju integrate my-charm:cos-agent grafana-agent
juju integrate grafana-agent grafana-k8s
juju integrate grafana-agent prometheus-k8s
juju integrate grafana-agent loki-k8s

# For K8s charms, use grafana-agent-k8s (sidecar).
juju deploy grafana-agent-k8s
juju integrate my-charm grafana-agent-k8s
```

Use `juju_offer`, `juju_consume`, and `juju_list_offers` tools for this.

## Step 6: Verify Observability

After deployment, verify:

1. **Traces** — check Tempo for spans from your charm's hook executions
2. **Metrics** — check Prometheus targets to confirm scraping is active
3. **Logs** — check Loki for workload log streams
4. **Dashboards** — open Grafana and find the auto-provisioned dashboard

### Smoke-testing COS integration from an integration test

For a regression-proof check that telemetry actually flows, write a
`pytest-jubilant` integration test that brings up COS Lite in a second
model and asserts that logs / metrics / traces arrive. The pattern lives
in the `jubilant-tests` skill under "Cross-model — COS Lite Integration":

- `pytest_jubilant.JujuFactory.get_juju(suffix="cos")` for the COS Juju.
- `cos.deploy("cos-lite", trust=True)` then `cos.wait(jubilant.all_active, timeout=10*60)`.
- Cross-model integrate: `cos.offer("loki", endpoint="logging")` then
  `juju.integrate(APP_NAME, f"{cos.model}.loki")`.
- Verify: run Traefik's `show-proxied-endpoints` action, parse the JSON,
  hit Loki/Prometheus/Tempo HTTP APIs to confirm the workload's labels
  are present.

This is worth adding once per charm — a single "logs reach Loki" test
catches the broad class of label / dispatcher / forwarding regressions
that don't show up in unit tests.

## Alertmanager — Routing and Receivers

Alertmanager is the COS component that takes firing alerts from
Prometheus and *routes* them to humans (PagerDuty, Slack, email,
webhooks).  Most charms never relate to Alertmanager directly —
they publish alert rules via `metrics-endpoint` (Step 2) and the
COS bundle wires Prometheus to Alertmanager automatically.

### Alert flow at a glance

```
[my-charm/0]
   │
   │ metrics-endpoint (prometheus_scrape)
   │    + alert rules from src/prometheus_alert_rules/
   ▼
[prometheus-k8s]
   │
   │ alertmanager (alertmanager_dispatch)
   ▼
[alertmanager-k8s]
   │
   │ alertmanager-dispatch (alertmanager_dispatch)
   ▼
[karma-k8s] / [slack-bot] / [pagerduty-bot] / ...
```

The charm author's job stops at the alert rules.  Operators
configure routing on the Alertmanager side via the
`alertmanager-k8s` charm's config options.

### Configuring routing on `alertmanager-k8s`

The COS bundle ships `alertmanager-k8s` with a default config
that drops alerts on the floor.  To wire it to a real receiver,
set `config.yaml` on the Alertmanager charm:

```bash
juju config alertmanager-k8s -m cos config_file=@alertmanager-config.yaml
```

```yaml
# alertmanager-config.yaml
route:
  receiver: default
  group_by: [alertname, juju_application]
  group_wait: 30s
  group_interval: 5m
  repeat_interval: 4h
  routes:
    - matchers:
        - severity = critical
      receiver: pager
    - matchers:
        - severity = warning
      receiver: slack

receivers:
  - name: default
    slack_configs:
      - api_url: https://hooks.slack.com/services/...
        channel: '#alerts'
  - name: pager
    pagerduty_configs:
      - service_key: <pagerduty-integration-key>
  - name: slack
    slack_configs:
      - api_url: https://hooks.slack.com/services/...
        channel: '#alerts-warnings'
```

The `juju_application` label is auto-injected by the COS topology
relabelling, so grouping and routing on it works out of the box.

### Karma — the alert-dashboard frontend

Karma (see References) is the standard Alertmanager visualiser
deployed alongside `alertmanager-k8s`
in the COS bundle.  Charm authors don't relate to Karma; users
open Karma's URL (find it via the bundle's Catalogue entry, or
``juju run alertmanager-k8s/0 show-config`` for the
proxied-endpoints) to see firing alerts grouped by
`juju_application` / `severity`.

### When a charm should require `alertmanager-dispatch`

The `alertmanager-dispatch` interface is for charms that want to
*receive* alerts — typically one of:

- A custom notification charm (in-house Slack bot, ChatOps,
  webhook handler).
- A meta-dashboard charm that needs to subscribe to firing
  alerts (Karma is the example).
- An incident-management charm that creates tickets from
  alerts.

These are rare; most charm authors don't need this side of the
relation.  When you do:

```yaml
# charmcraft.yaml
requires:
  alerting:
    interface: alertmanager_dispatch
    limit: 1
```

```python
from charms.alertmanager_k8s.v1.alertmanager_dispatch import AlertmanagerConsumer


class MyNotifierCharm(ops.CharmBase):
    def __init__(self, framework: ops.Framework):
        super().__init__(framework)
        self._alertmanager = AlertmanagerConsumer(
            self,
            relation_name="alerting",
        )
        framework.observe(
            self._alertmanager.on.cluster_changed,
            self._on_alertmanager_cluster_changed,
        )

    def _on_alertmanager_cluster_changed(self, _event):
        urls = self._alertmanager.get_cluster_info()
        # Configure the notifier workload with the Alertmanager URLs.
```

The `charms.alertmanager_k8s.*` library is **not on PyPI yet**;
fetch it via `charmcraft fetch-libs`.

### Production routing tips

- **Group by `juju_application`** so an outage on one charm doesn't
  flood the receiver with one notification per unit.
- **`severity` labels in alert rules** become the Alertmanager
  routing key — keep the levels coarse (`info` / `warning` /
  `critical`) so routes stay readable.
- **`for:` durations matter** — flapping alerts that fire and
  resolve within seconds aren't actionable.  10 minutes is a
  sensible floor for warnings; criticals can be tighter.
- **Inhibit rules suppress noise** — when a `service_down` alert
  fires, the Alertmanager `inhibit_rules` config can mute the
  cascading "high error rate" alerts that always follow.  Add
  inhibitions to the alertmanager-k8s config when the alert
  graph has obvious dependencies.

## Sloth — SLOs and Burn-Rate Alerts

Sloth turns a small per-charm `slos.yaml` into multi-window burn-rate
Prometheus rules; the resulting alerts ride the same
`metrics-endpoint` → Prometheus → Alertmanager path Step 2 and the
section above already wire.  No new scrape targets and no new
receivers — one extra relation plus a YAML file.

Default SLOs by workload type (tune to the user's reliability budget):

| Workload kind | Suggested SLOs |
|---------------|----------------|
| **12-factor PaaS** (Path A) | HTTP availability (non-5xx ratio) at 99.5% / 30d; p95 request latency at 99% / 30d |
| **Infrastructure charm** (Path C) | Hook success ratio at 99.9% / 30d; p95 hook duration under 30s at 99% / 30d |
| **Custom app** (Path B) | Workload availability (Pebble check ratio) at 99% / 30d, plus any workload-specific SLO the user asks for |

```yaml
# charmcraft.yaml — interface from charmlibs-interfaces-sloth
requires:
  slos:
    interface: slos
    limit: 1
```

### Worked example — 12-factor charm

One availability SLO over a 30-day window; a latency SLO follows the
same shape using `http_request_duration_seconds_bucket{le="0.5"}` over
`http_request_duration_seconds_count`.

```yaml
# src/slos.yaml
version: prometheus/v1
service: my-app
labels:
  juju_charm: my-charm
slos:
  - name: requests-availability
    objective: 99.5
    description: 99.5% of HTTP requests return a non-5xx response over 30d.
    sli:
      events:
        error_query: |
          sum(rate(http_requests_total{
            juju_application="my-app", status=~"5.."}[{{.window}}]))
        total_query: |
          sum(rate(http_requests_total{
            juju_application="my-app"}[{{.window}}]))
    alerting:
      name: MyAppHighErrorRate
      page_alert:
        labels: {severity: critical}
      ticket_alert:
        labels: {severity: warning}
```

The `juju_application` filter is the topology label COS auto-injects
on every forwarded metric, so Sloth's alerts share the label space the
dashboards and Alertmanager routes already use.  `{{.window}}` is
Sloth's own templating — leave it verbatim; Sloth substitutes the
burn-rate windows (5m / 30m / 1h / 6h / 1d / 3d) when generating the
multi-window rules.  Infrastructure charms swap the queries for the
`juju_hook_*` metrics auto-exposed by ops-tracing.

### Charm-side relation handler

```python
import ops
from charmlibs.interfaces import sloth


class MyCharm(ops.CharmBase):
    def __init__(self, framework: ops.Framework):
        super().__init__(framework)
        self._slos_path = self.charm_dir / "src" / "slos.yaml"
        framework.observe(self.on["slos"].relation_joined, self._publish_slos)
        framework.observe(self.on["slos"].relation_changed, self._publish_slos)

    def _publish_slos(self, event: ops.RelationEvent) -> None:
        if not self._slos_path.exists():
            return
        spec = sloth.SlosSpec.from_yaml(self._slos_path.read_text())
        sloth.publish(event.relation, spec, app=self.app)
```

### Notes

- **Pick the objective for the SLI, not the brand.**  99.99% on an
  internal admin tool is a missed alert; use the lowest target that
  still catches outages users would complain about.
- **Page vs ticket via burn rate.**  Match `page_alert` to
  `severity: critical` and `ticket_alert` to `severity: warning` so
  the Alertmanager routes from the previous section dispatch
  fast-burn pages and slow-burn tickets correctly.
- **Retire duplicate hand-written rules.**  When an SLO covers a
  condition (`HighWorkloadErrorRate` from the earlier example is
  one), drop the single-window threshold; the burn-rate alert fires
  faster on sharp burns and quieter on shallow ones.  Keep
  hand-written rules for non-SLO conditions only.
- **Store `slos.yaml` next to the charm code.**  Mirror
  `src/grafana_dashboards/`; `src/slos.yaml` per charm is the
  convention.

## Catalogue — Landing-Page Registration

`catalogue-k8s` builds the COS landing page.  When a charm exposes
a UI (workload dashboard, admin endpoint, the Grafana panel for the
workload), relating to Catalogue puts that URL on a discoverable
list.  The interface carries four fields: `name`, `description`,
`url`, and `icon` (the icon name; `catalogue-k8s` serves the asset).

```yaml
# charmcraft.yaml
provides:
  catalogue:
    interface: catalogue
```

```python
from charms.catalogue_k8s.v1.catalogue import CatalogueConsumer, CatalogueItem


class MyCharm(ops.CharmBase):
    def __init__(self, framework: ops.Framework):
        super().__init__(framework)
        self._catalogue = CatalogueConsumer(
            charm=self,
            item=CatalogueItem(
                name="My App",
                description="The thing we run.",
                url=self._ingress.url or "",
                icon="my-app",
            ),
        )
```

`url` is typically the Traefik-fronted external URL from the
`ingress` relation, so the entry stays in sync when Traefik
re-issues the route.  Call `_catalogue.update_item(...)` from the
ingress `relation-changed` handler when the URL changes.
`charms.catalogue_k8s.*` is not on PyPI yet — fetch with
`charmcraft fetch-libs`.

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

5. **Fetch libraries from PyPI first.** `ops-tracing` and `cosl` (COS
   Lite utilities — topology labels, Loki logging handler, cos-tool
   bindings) are on PyPI.  The individual observability *charm*
   libraries (``charms.loki_k8s.*``, ``charms.grafana_k8s.*``,
   ``charms.prometheus_k8s.*``, ``charms.traefik_k8s.*``,
   ``charms.tempo_*``, ``charms.catalogue_k8s.*``,
   ``charms.observability_libs.*``) have **no PyPI equivalent yet**
   and still require ``charmcraft fetch-libs``.  Interface schemas
   (``charmlibs-interfaces-*``) and low-level utilities
   (``charmlibs-apt``, ``charmlibs-pathops``, etc.) are on PyPI — see
   the ``charmcraft`` skill for the full list.

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

## References

- Karma — https://karma-dashboard.io/ (Alertmanager dashboard frontend)
- Sloth — https://sloth.dev/ (Prometheus SLO rule generator)
