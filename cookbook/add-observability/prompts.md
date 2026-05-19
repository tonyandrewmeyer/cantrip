# Add-observability prompts

Paste these into Cantrip in order, from the charm's directory. Wait
for each autonomous run to complete before pasting the next.

## 1 — Audit the gaps

```
Load the observability skill and audit this charm's COS integration.
Run charm_audit (or charmlint) and tell me what's missing: ops-tracing,
a metrics-endpoint relation, a logging relation, a grafana-dashboard
relation, alert rules, dashboards. Don't change anything yet.
```

This grounds Cantrip in the COS conventions and produces the
baseline it will work down.

## 2 — Wire in the full COS surface

```
Now add the full COS surface:

- ops-tracing: add the dependency, the `tracing` relation to
  charmcraft.yaml, and `ops_tracing.Tracing(self, "tracing")` in
  src/charm.py.
- metrics: a metrics-endpoint relation with MetricsEndpointProvider,
  plus at least one Prometheus alert rule under
  src/prometheus_alert_rules/.
- logs: a logging relation with the Loki consumer/forwarder.
- dashboards: a grafana-dashboard relation with GrafanaDashboardProvider
  and at least one dashboard JSON under src/grafana_dashboards/.

If this is a machine (not K8s) charm, a single cos-agent relation
with COSAgentProvider covers metrics + logs + dashboards — use that
instead of the three separate relations.
```

## 3 — Confirm done

```
/tasks
```

```
Run charm_validate: unit tests pass, the COS relations are all
declared in charmcraft.yaml, the matching providers/consumers are
instantiated in src/charm.py, a dashboard ships under
src/grafana_dashboards/, and packing succeeds.
```

Then run the verifier:

```bash
python /path/to/cantrip/cookbook/add-observability/verify.py .
```

## Optional — deploy and check the relations

If you have a Juju controller with COS (e.g. a `cos-lite` model):

```
Deploy this charm to the dev model, relate it to COS — tracing,
metrics, logging, dashboards (or cos-agent) — wait for active/idle,
and confirm the relations are joined.
```

## Optional — commit

```
git_add the changed files (charmcraft.yaml, src/charm.py, the deps
manifest, src/grafana_dashboards/, src/prometheus_alert_rules/),
git_commit with the message "Add COS observability integration".
```
