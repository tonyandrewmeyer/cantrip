---
title: "Observability and debugging — Cantrip"
description: "How Cantrip uses COS, Tempo, and Loki to instrument and debug charms autonomously."
h1: "Observability and debugging"
subtitle: "Cantrip does not just add observability to your charm — it uses observability data to debug problems autonomously."
section: explanation
breadcrumb_label: "Observability and debugging"
on_this_page:
  - { anchor: "why", label: "Why observability matters" }
  - { anchor: "cos", label: "COS integration" }
  - { anchor: "instrumentation", label: "Charm instrumentation" }
  - { anchor: "debugging", label: "Autonomous debugging" }
  - { anchor: "watcher", label: "The event watcher" }
---

{#why}
## Why observability matters for an agent

When a charm enters an error state after deployment, a human
developer would check logs, look at traces, and inspect the unit.
Cantrip does the same thing, but automatically. Observability is
not just a feature the agent adds to your charm; it is how the
agent understands what is happening during deployment and testing.

This is why COS integration is not optional in Cantrip. Every charm
the agent builds includes observability from the start, because the
agent needs it to do its job.

{#cos}
## COS integration

**COS-lite** (Canonical Observability Stack) provides
Prometheus for metrics, Loki for logs, Tempo for distributed traces,
and Grafana for dashboards. Cantrip deploys COS-lite into a
separate Juju model and creates cross-model relations to your
charm's model.

This architecture keeps the observability stack isolated from
your workload while still receiving all telemetry data. The agent
handles the cross-model setup automatically, including offers and
consumers.

{#instrumentation}
## Charm instrumentation

Every charm built by Cantrip includes **ops-tracing**,
which instruments the ops framework to emit distributed traces for
every hook execution. This gives the agent (and you) visibility into:

- Which hooks fired and in what order
- How long each hook took to execute
- Which framework methods were called within each hook
- Where exceptions occurred

The agent also wires up Prometheus metrics endpoints where the
workload supports them, and configures Loki log forwarding so
application logs are available alongside Juju logs.

{#debugging}
## Autonomous debugging

When a deployment fails or a charm enters an error or blocked state,
the agent creates a diagnostic task and uses observability tools to
investigate:

1. **Tempo queries** — the agent queries Tempo for
   recent traces, looking for failed spans, long durations, or
   unexpected hook sequences. Traces often reveal the exact line of
   code that raised an exception.
2. **Loki queries** — the agent queries Loki for
   error-level log messages from both Juju and the workload. Log
   messages provide context that traces alone may not capture.
3. **Juju debug-log** — as a fallback when COS is
   not yet available, the agent reads the Juju debug log directly
   for hook errors and status messages.

Based on what it finds, the agent creates a fix task, modifies the
code, repacks, and redeploys. This cycle repeats until the charm
reaches active/idle or the agent exhausts its retry budget.

{#watcher}
## The event watcher

The watcher is an optional component (`--watcher` flag)
that monitors the Juju model in real time. It polls for status
changes and creates tasks automatically when something interesting
happens:

- **Status changes** — if a unit transitions from
  active to error, the watcher creates a diagnostic task.
- **New log entries** — the watcher polls Loki for
  new error-level entries and surfaces them as tasks.

The watcher is useful during iterative development and testing. It
turns Cantrip into a continuously watching agent that reacts to
changes in the model without you needing to notice or report them.

In the TUI you can press <kbd>F5</kbd> to pause and resume those
autonomous reactions. While paused, the watcher keeps observing — the
model panes still refresh and `[Watcher]` notices still appear in the
chat — but detected events no longer queue tasks, so the agent stops
acting on them on its own. Useful when you want to debug the model by
hand without the agent jumping in. The status bar shows
`👁 Watching` normally and `👁 Watching (paused)` while reactions are
suspended.

See also:

- [How Cantrip works](explanation-architecture.html)
- [Observability tools reference](reference-tools.html#observability)
