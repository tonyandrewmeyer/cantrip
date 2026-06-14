# Stateful-charm prompts

Paste these into Cantrip in order. Wait for each autonomous run to
complete before pasting the next. Replace `<NAME>` and `<WORKLOAD>`
with your target (e.g. `<NAME>` = `widget-store`, `<WORKLOAD>` = a
PostgreSQL-backed inventory service).

## 1 — Kick off the full build

```
Build me a production-quality <NAME> charm for <WORKLOAD>.

This is the full path, not sprint mode: I want Scenario unit tests,
ops-tracing instrumentation, COS integration (metrics, logs, a
Grafana dashboard, alert rules), and Jubilant integration tests.
The workload is stateful, so cover storage-attached and
collect-status branches.

Design it first, show me the design document, and wait for my
approval before generating build tasks.
```

Do **not** use a `Sprint build:` prefix here — that would dispatch
the fast path. The plain build prompt takes the full flow:
research → design → build → deploy → test → day-2 research.

## 2 — Approve the design

Cantrip presents a design document and blocks. Review it, then:

```
The design looks good. Generate the build tasks and start.
```

Adjust first if you need to (`use machine instead of K8s`,
`skip the ingress relation`, etc.) — overrides flow through to the
build tasks.

## 3 — Steer if needed

While the build runs you can nudge it:

```
Make sure ops_tracing.Tracing(self, "tracing") is wired and the
tracing relation is in charmcraft.yaml. Add a Grafana dashboard
under src/grafana_dashboards/ and at least one Prometheus alert
rule under src/prometheus_alert_rules/.
```

```
The collect-status handler needs a negative test: storage detached
should produce WaitingStatus, not ActiveStatus.
```

## 4 — Deploy and test

If Cantrip stopped at packing (no controller, or you declined the
deploy), and you do have a Juju controller with COS:

```
Deploy <NAME> to the dev model, relate it to COS (tracing, metrics,
logging, dashboards), wait for active/idle, then run the Jubilant
integration tests against it.
```

## 5 — Confirm done

```
/tasks
```

```
Run charm_validate: unit tests pass, coverage holds above the 80%
floor, integration tests pass, and packing succeeds. Confirm
ops-tracing is instrumenting hooks and the COS relations are all
declared.
```

Then run the verifier yourself:

```bash
python /path/to/cantrip/cookbook/build-a-stateful-charm/verify.py .
```

## Optional — commit

```
git_init, git_add everything including uv.lock, git_commit with the
message "Full build of <NAME> — Scenario tests, ops-tracing, COS".
```

The full flow usually commits as it goes; this is only needed if a
run stopped before the final commit.
