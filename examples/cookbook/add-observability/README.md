# Add observability to an existing charm

**Wire a charm into the Canonical Observability Stack.** Traces from
charm code, Prometheus metrics, Loki logs, Grafana dashboards — all
through standard Juju relations, so deploying alongside `cos-lite`
lights everything up. This recipe drives Cantrip's `observability`
skill to add that surface to a charm that doesn't have it (or only
has part of it).

Use it for:

- A charm you've built or inherited that's running blind — no
  tracing, no metrics relation, no dashboard.
- Closing the COS gaps a `charm_audit` flags.
- Onboarding to the COS conventions — the verifier spells out the
  full set.

This is the observability slice of [`build-a-stateful-charm/`](../build-a-stateful-charm/README.md)
as a standalone, improve-style recipe: run it against an existing
charm directory rather than building one from scratch.

## What you need

- **Cantrip** installed (`uv sync --dev && uv pip install -e .`
  from the Cantrip repo, or however you usually do it).
- **An existing charm** — a `charmcraft.yaml` and `src/charm.py` at
  minimum.
- **`uv`** on `$PATH` — adding `ops-tracing` and the COS charm libs
  touches the dependency manifest, then re-syncs.
- **A Juju controller with COS** only if you want to deploy and see
  the relations come up. The recipe and its verifier don't need
  one — they check files on disk.

## What you get

The charm gains:

```
<charm-dir>/
├── charmcraft.yaml          # tracing relation + metrics-endpoint + logging + grafana-dashboard
│                            #   (or, for a machine charm, a single cos-agent relation covering all three)
├── pyproject.toml           # ops-tracing dependency (+ the COS charm libs)
├── src/
│   ├── charm.py             # ops_tracing.Tracing(self, "tracing"); MetricsEndpointProvider /
│   │                        #   GrafanaDashboardProvider / LokiPushApiConsumer (or COSAgentProvider)
│   ├── grafana_dashboards/  # at least one dashboard JSON
│   └── prometheus_alert_rules/   # alert-rule YAML (rides along the metrics-endpoint relation)
```

**Machine vs K8s.** For a K8s charm you'll typically see three
separate relations (`metrics-endpoint`, `logging`,
`grafana-dashboard`) plus their providers. For a machine charm a
single `cos-agent` relation with `COSAgentProvider` carries metrics,
logs, *and* dashboards — the verifier accepts either.

## Walkthrough

1. From the charm's directory, start Cantrip:
   ```bash
   cd ~/charms/my-charm
   cantrip .
   ```

2. Paste the prompts from [`prompts.md`](prompts.md) one at a time.
   Wait for each autonomous run to finish before the next paste.

3. When Cantrip reports COS is wired in, verify the shape:
   ```bash
   python /path/to/cantrip/cookbook/add-observability/verify.py .
   ```

   You should see `OK — COS integration shape verified (tracing +
   metrics + logs + dashboards).` with exit code 0. Failures print a
   short reason naming the missing piece.

4. If you have a Juju controller with COS, deploy and check the
   relations come up:
   ```
   Deploy this charm to the dev model, relate it to COS (tracing,
   metrics, logging, dashboards), wait for active/idle, and confirm
   the relations are joined.
   ```

## How the verifier works

[`verify.py`](verify.py) loads the charm directory and asserts:

- It's still a charm — `charmcraft.yaml` (valid YAML, named) plus
  `src/charm.py`.
- **ops-tracing is wired up** — `ops-tracing` (or `ops[tracing]`) is
  a dependency; `src/charm.py` references the `ops_tracing` module;
  and `charmcraft.yaml` declares a `tracing` relation.
- **The metrics, logs, and dashboard relations are all present** —
  separate `metrics-endpoint` / `logging` / `grafana-dashboard`
  endpoints (by name or interface), or a single `cos-agent` relation
  covering all three.
- **At least one Grafana dashboard ships** — a populated
  `src/grafana_dashboards/` directory.
- **The COS provider libraries are actually wired** — `src/charm.py`
  references at least one of `MetricsEndpointProvider`,
  `GrafanaDashboardProvider`, `LokiPushApiConsumer`,
  `LogProxyConsumer`, `LogForwarder`, `COSAgentProvider`.

It does not run anything — packing and deploying need a real
environment. The verifier is a shape contract, not an integration
harness.

## Why this recipe is in the cookbook

"Production charm" and "observable charm" are nearly synonyms in the
Canonical ecosystem, and the `observability` skill commits to a
specific COS surface. Pinning that surface in a verifier gives us:

1. **Teaching artifact** — `verify.py` is a checklist of what
   "observable" means: tracing wired, all three COS relations,
   dashboards shipped, providers instantiated.
2. **Regression fixture** — if the skill drifts (a relation gets
   renamed, a provider class is replaced, the dashboards path
   moves), the verifier and the recipe disagree and CI's structure
   sweep over `cookbook/*/` flags it.

## Related

- Cantrip's `observability` skill — the in-agent guidance behind
  the COS surface (relation names, provider classes, alert rules).
- [`build-a-stateful-charm/`](../build-a-stateful-charm/README.md)
  — builds a charm with this observability surface from the start.
- [`migrate-harness-to-scenario/`](../migrate-harness-to-scenario/README.md)
  — the other improve-style recipe; modernises the test suite.
