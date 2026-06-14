# Build a stateful charm

**The full path — the counterpart to [`build-a-sprint-charm/`](../build-a-sprint-charm/README.md).**
Where the sprint recipe skips tests, observability, and tracing to
ship a `.charm` in under a minute, this recipe drives the build
Cantrip commits to for a charm you'd actually run: state-transition
(Scenario) unit tests, ops-tracing instrumentation, COS integration
(metrics + logs + dashboards), and Jubilant integration tests.

"Stateful" is the case that *needs* this ceremony — a workload that
persists data (a database, a queue, a cache) has storage-attached
and collect-status branches to cover, peer relations for HA, and
operational surface (backup, scaling) that only shows up under load.
The recipe works for any production charm; a stateful workload is
just the one where cutting corners hurts soonest.

Use it for:

- A workload you'll deploy beyond a throwaway dev model.
- Anything you intend to list on Charmhub.
- Onboarding to the *full* Cantrip workflow (the sprint recipe
  onboards you to the toolchain; this one onboards you to the
  quality bar).

## What you need

- **Cantrip** installed (`uv sync --dev && uv pip install -e .`
  from the Cantrip repo, or however you usually do it).
- **charmcraft** on `$PATH`.
- **A Canonical-style container runtime** for destructive-mode
  packing (`concierge`, or `sudo snap install lxd && lxd init --auto`).
- **A Juju controller with COS** for the deploy + integration-test
  steps. `concierge` can bootstrap one; or bring your own and a
  `cos-lite` (or `cos`) model. *Without* a controller you can still
  run the recipe up to packing — the verifier checks files on disk,
  not a running model.

## What you get

A charm directory with this shape:

```
<charm-dir>/
├── charmcraft.yaml          # tracing relation + metrics/logging/grafana-dashboard relations
├── pyproject.toml           # ops-tracing dep; uv.lock committed alongside
├── src/
│   ├── charm.py             # ops_tracing.Tracing(self, "tracing"); metrics/logs/dashboard providers
│   ├── grafana_dashboards/  # at least one dashboard JSON
│   └── prometheus_alert_rules/   # at least one alert-rule YAML
├── tests/
│   ├── unit/                # Scenario tests: ctx.run(ctx.on.<event>(...), state); no Harness
│   └── integration/         # Jubilant tests: jubilant.Juju(...).deploy(...) + status asserts
└── <name>_*.charm           # the packed charm
```

The exact endpoint names and the workload-specific code vary; the
*invariants* the verifier checks don't.

## Walkthrough

1. Pick an empty directory:
   ```bash
   mkdir ~/charms/my-stateful && cd ~/charms/my-stateful
   ```

2. Start Cantrip:
   ```bash
   cantrip .
   ```

3. Paste the prompts from [`prompts.md`](prompts.md) one at a time.
   Wait for each autonomous run to finish before the next paste.
   This is the full flow — design → build → deploy → test → day-2
   research — so it takes longer than the sprint recipe; that's the
   point.

4. When Cantrip reports the charm is built and tested, verify the
   shape:
   ```bash
   python /path/to/cantrip/cookbook/build-a-stateful-charm/verify.py .
   ```

   You should see `OK — full-build shape verified (tests + tracing
   + COS).` with exit code 0. Failures print a short reason naming
   the missing piece.

5. Run the suites yourself for the behavioural check:
   ```bash
   uv run pytest tests/unit/
   # integration tests need a live controller + COS:
   uv run pytest tests/integration/
   ```

## How the verifier works

[`verify.py`](verify.py) loads the charm directory and asserts:

- `charmcraft.yaml` exists, is a valid YAML mapping, and names the
  charm; `src/charm.py` exists.
- **ops-tracing is wired up** — `ops-tracing` (or `ops[tracing]`)
  appears in `pyproject.toml` / `requirements.txt`; `src/charm.py`
  references the `ops_tracing` module; and `charmcraft.yaml`
  declares a `tracing` relation (a `tracing` / `charm-tracing`
  endpoint, or one with `interface: tracing`).
- **COS integration beyond tracing** — at least one metrics /
  logs / dashboard relation (`metrics-endpoint`, `logging`,
  `grafana-dashboard`, …, or an `interface:` in that family), or a
  populated `src/grafana_dashboards/` / `src/prometheus_alert_rules/`
  / `src/loki_alert_rules/` directory.
- **Scenario unit tests** — `tests/` holds `.py` files, at least
  one uses a state-transition construct (`testing.Context` /
  `testing.State` / `ctx.run(...)`), and none uses the deprecated
  `ops.testing.Harness`.
- **Jubilant integration tests** — a `tests/integration/` directory
  with `.py` files, or a test file that imports `jubilant`.

It does not run anything — packing and the test suites need a real
environment. The verifier is a shape contract, not an integration
harness.

## Why this recipe is in the cookbook

Sprint mode and the full build are the two shapes Cantrip's
autonomous loop commits to. The sprint shape is pinned by
`build-a-sprint-charm/verify.py`; this verifier pins the other end.
Together they give us:

1. **Teaching artifact** — reading both verifiers side by side
   shows exactly what you trade away by choosing the fast path:
   tests, tracing, COS.
2. **Regression fixture** — if a planner / scaffolding change drops
   ops-tracing from the full path, stops generating Scenario tests,
   or quietly skips COS wiring, this verifier catches it.

## Related

- [`build-a-sprint-charm/`](../build-a-sprint-charm/README.md) — the
  fast path; the inverse of this recipe.
- Cantrip's `observability`, `scenario-tests`, and `jubilant-tests`
  skills — the in-agent guidance behind tracing, Scenario unit
  tests, and Jubilant integration tests.
- `design/AGENT.md` § *Subagent Pattern* — how Cantrip dispatches
  full builds.
