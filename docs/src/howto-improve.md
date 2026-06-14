---
title: "How to improve an existing charm — Cantrip"
description: "Use Cantrip's improve mode to audit and upgrade an existing Juju charm."
h1: "Improve an existing charm"
subtitle: "Audit and upgrade a charm you have already written, adding tests, observability, and modern patterns."
section: howto
breadcrumb_label: "Improve an existing charm"
---

{#when}
## When to use improve mode

Use `--improve` when you have an existing charm that needs:

- An audit against current best practices
- Missing unit or integration tests
- COS integration (traces, metrics, dashboards)
- Deprecated API replacements (e.g. Harness → Scenario)
- Operational readiness evaluation
- Preparation for Charmhub listing

<div class="callout">
  <p>
    For the Harness → Scenario case specifically, there is a
    step-by-step recipe with copy-paste prompts and a verifier you can
    run against the result:
    <a href="https://github.com/tonyandrewmeyer/cantrip/tree/main/examples/cookbook/migrate-harness-to-scenario" target="_blank" rel="noopener"><code>examples/cookbook/migrate-harness-to-scenario/</code></a>.
    The <a href="https://github.com/tonyandrewmeyer/cantrip/tree/main/examples/cookbook" target="_blank" rel="noopener"><code>examples/cookbook/</code></a> directory collects more of these runnable workflows.
  </p>
</div>

{#run}
## Run the improvement

Point Cantrip at your existing charm directory:

<pre><code><span class="prompt">$</span> cantrip --improve /path/to/my-existing-charm</code></pre>

Cantrip reads the existing code and configuration, then creates a
plan of improvements. You will see a proposal in the chat listing
what the agent intends to change. Confirm or adjust the plan before
the agent begins work.

{#what-happens}
## What the agent does

In improve mode the agent typically follows this sequence:

1. **Audit** — reads all charm files, runs
   `charmlint`, checks metadata, and evaluates against
   Operational Readiness Metrics.
2. **Propose** — presents a prioritised list of
   improvements with rationale.
3. **Implement** — after your confirmation,
   subagents work through the list: adding tests, wiring up
   observability, replacing deprecated patterns.
4. **Redeploy and test** — packs the updated charm,
   deploys it, and runs the new test suite.

{#steering}
## Steering the improvements

You can guide the agent during the improvement process:

- "Focus on testing only" — skip other categories.
- "Don't touch the config options" — exclude specific areas.
- "Add backup and restore actions" — request specific
  enhancements beyond what the audit found.

{#git}
## Working with git

The agent commits at appropriate points during the improvement. Each
commit is a self-contained change (e.g. "add COS integration",
"replace Harness tests with Scenario"). You can review the commits
afterwards and cherry-pick or squash as needed.

<div class="callout">
  <p>
    Improve mode works on the charm directory in place. If you want to
    preserve the original state, create a git branch or copy the
    directory before running.
  </p>
</div>
