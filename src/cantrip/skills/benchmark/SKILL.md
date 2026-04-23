---
name: benchmark
description: Measuring charm hook performance with hook_benchmark and comparing before/after snapshots across optimisation work
---

# Charm Benchmarking

Use this skill when the user asks about charm *performance* — slow
deployments, long reconcile cycles, hooks that time out, or a
regression that's crept in between charm versions. It wraps the
`hook_benchmark` tool with an interpretation guide and prescribes the
before/after comparison pattern for optimisation work.

## When to load

- The user says "my charm is slow", "deploy takes forever", "hooks
  keep timing out", or asks for a performance benchmark.
- You have just finished an optimisation change and want to verify
  the numbers moved in the right direction.
- A regression test suite needs a performance baseline committed.

If the user is diagnosing a *broken* charm rather than a slow one,
load the `charm-debug` skill instead. Benchmarking is only
interesting once the charm actually reaches `active`.

## What `hook_benchmark` measures

`hook_benchmark` reads `juju debug-log` and extracts every
`ran "<hook>" hook (<duration_ms>ms)` line emitted by Juju's
uniter. It then reports:

- **Per-hook statistics** — count, min, max, and mean duration in
  milliseconds, one row per hook name.
- **Slow-hook callout** — every hook whose *maximum* exceeds the
  `threshold_ms` argument (default 5000 ms) is flagged. The cutoff
  reflects Juju's 5-second implicit timeout for hook retries — past
  that point you're observably slow to the operator.
- **Structured `data.timings`** — the raw list of
  `{unit, hook, duration_ms}` dicts so you can do your own maths
  over the output (the before/after pattern below uses these).

What it **does not** measure:

- Workload latency inside Pebble services — that's not a hook.
- Action execution times — not logged with the `ran "<hook>"`
  prefix. For action profiling, wrap the action body yourself with
  a Python timer and emit a log line.
- Cold-start CPU cost on the machine / pod; use `juju ssh` +
  `top` for that.

## Capturing a benchmark

Deploy the charm, exercise every hook you care about, then call the
tool:

```
hook_benchmark(app="my-charm", lines=1000, threshold_ms=5000)
```

Parameters worth setting explicitly:

- `app` — always scope the report to one application. Cross-app
  comparisons are misleading because of different workloads.
- `lines` — default 500 is fine for a fresh deploy; bump to 2000+
  if you're looking at a long-running unit where `install` /
  `config-changed` is buried in history.
- `threshold_ms` — 5000 is the default sound alarm; lower to 1000
  for an optimisation target (you want to see what's slowing down
  *before* it becomes a Juju retry risk).

Exercise every hook you care about before calling the tool — the
tool can only report hooks Juju actually observed, so if you never
touched config since deploy, `config-changed` will be missing.

Typical exercising sequence:

```
juju_deploy(...)                          # fires install, start
juju_wait(status="active")                # lets collect-status settle
juju_config(set={"log-level": "debug"})   # fires config-changed
juju_relate("my-charm:db", "postgres:db") # fires relation-changed
juju_dispatch(unit="my-charm/0",
              event="update-status")      # fires update-status on demand
```

## Interpreting the report

The per-hook average tells you what the hook *usually* costs; the
per-hook max tells you what it costs in the worst case. Optimise
against the max — a hook that averages 200 ms but spikes to 8
seconds is going to trip retries eventually.

Rules of thumb for where the time is going:

- **`install` > 30 s** — usually image pull on K8s or apt/snap
  install on machine. Ship the dependency in the resource rather
  than fetching it inside the hook.
- **`config-changed` > 2 s** — probably writing a Pebble layer or
  systemd unit and restarting on every run. Diff the new config
  against the old and skip the restart if nothing changed.
- **`update-status` > 1 s** — every time this fires, usually every
  5 minutes. 1 s × N units × 12/hour adds up. Cache the workload
  probe result.
- **`*_relation_changed` > 500 ms** — often JSON-parsing an oversize
  databag, or a secret fetch. Memoise the parse for the duration of
  the hook.
- **`collect-status` > 500 ms** — status handlers should be pure
  reads, not Pebble exec calls. Move the expensive probe to the
  handler that *generates* the status, not the collector.

A hook that appears in the report **but does not appear** in your
exercising sequence usually means the charm observes more events
than it needs to. Cross-reference against `src/charm.py`.

## Before/after comparison across versions

The phase-33.6 ask is to compare across charm versions — before vs.
after an optimisation. The pattern is:

1. **Baseline**: deploy the *current* charm, exercise the hooks,
   call `hook_benchmark` with `threshold_ms=1000`. Save the
   `data.timings` list verbatim (commit it into
   `tests/perf/baseline.json` or hold it in a scratch note).
2. **Optimise**: make the change. Commit.
3. **Candidate**: redeploy (or refresh), exercise the same hooks,
   call `hook_benchmark` again with the same `threshold_ms`.
4. **Compare**: for each hook present in both runs, compute
   `delta_ms = candidate_avg - baseline_avg`. Flag hooks where the
   delta is worse than +10% of baseline or +100 ms (whichever is
   bigger) so noise doesn't look like a regression.
5. **Report**: a Markdown table keyed by hook name, with baseline
   avg, candidate avg, delta, and a verdict (`faster`, `same`,
   `slower`). Bold the row the optimisation was targeting so the
   user can confirm you moved *that* number, not just some
   unrelated one.

Example report shape:

```
| Hook             | Baseline avg (ms) | Candidate avg (ms) | Delta   | Verdict |
|------------------|-------------------|--------------------|---------|---------|
| install          | 12400             | 11200              | -1200   | faster  |
| config-changed   | 850               | 440                | -410    | faster  |
| **update-status**| **1800**          | **220**            |**-1580**| faster  |
| start            | 210               | 230                | +20     | same    |
```

For charms under a `cantrip.workspace.yaml` manifest, run the
before/after against each charm independently — cross-charm timings
don't add up cleanly because workload interactions dominate.

## What a "good enough" charm looks like

When the user asks "is my charm fast enough?", compare against these
rough ceilings; hooks below them don't need optimisation:

| Hook | Ceiling |
| --- | --- |
| `install` | 60 s (K8s) / 120 s (machine) |
| `start` | 2 s |
| `config-changed` | 500 ms |
| `update-status` | 300 ms |
| `*_relation_changed` | 500 ms |
| `collect-status` | 200 ms |
| `stop` | 5 s |

These are targets, not hard limits — a 700 ms `config-changed` is
fine for a charm that reconfigures Pebble and the workload. Treat
them as "if you're above this, double-check the hook body before
moving on".

## Committing a performance baseline to a charm

If the user wants to guard against regressions, the durable pattern
is:

1. Commit the baseline JSON into `tests/perf/baseline.json`.
2. Add a nightly Jubilant integration test that deploys the charm,
   exercises the hooks, calls `hook_benchmark`, and compares
   against the baseline using the same delta-threshold rule as
   above.
3. CI fails the job if any hook regresses beyond the threshold.
4. Optimisation commits update the baseline JSON in the same commit
   as the code change.

Do not commit raw timings for hooks Juju runs opportunistically
(e.g. `leader-elected`). Include only the hooks the user controls.

## References

- `hook_benchmark` tool — the underlying data source this skill
  wraps.
- `charm-debug` skill — for broken charms; benchmarking assumes
  the charm works and you're tightening the loop.
- `find-bugs` skill — some slow hooks are in fact bugs (missing
  Pebble timeouts, unguarded workload probes); diagnose via both
  skills when timings look pathological.
- `observability` skill — COS tracing (via `ops-tracing`) gives
  sub-hook breakdowns that `hook_benchmark` cannot; prefer Tempo
  for per-span attribution once COS is wired up.
