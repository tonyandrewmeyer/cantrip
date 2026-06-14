# Building ntfy from scratch — the hero demo

*Companion to [`demos/recordings/hero-ntfy.cast`](recordings/hero-ntfy.cast)*

This is the longest demo in the set: Cantrip taking the from-scratch ntfy charm — a self-hosted push notification server — through the **research → synthesis → design** phase that opens every full-path build.  The cast captures the autonomous research subagents working in parallel against the upstream sources, then the synthesis subagent producing a design proposal for operator review.

The build/deploy/test continuation that produces the final ops-tracing-, COS-, and test-rich charm runs after the design is confirmed.  Print and CLI modes don't yet auto-resolve the design-confirmation gate the planner inserts after synthesis — the build half is therefore best driven from the TUI today.  The clip's natural endpoint is the design proposal landing in the chat.

ntfy is a Path B custom charm (single Go binary, YAML config file, persistent state, Prometheus metrics) and is also one of Cantrip's gold-standard reference targets, so the resulting charm is verified against a checked-in rubric covering structure, metadata, code shape, observability, and tests.

## Pre-flight

The build runs against a real Juju environment.  Sanity-check the controller is reachable before recording:

```bash
juju version
```

```output
3.6.21-genericlinux-amd64
```

```bash
juju controllers --refresh 2>&1 | head -3
```

```output
Controller      Model       User   Access     Cloud/Region         Models  Nodes    HA  Version
concierge-k8s*  cantrip-r3  admin  superuser  k8s                       4      -     -  3.6.21
```

## The prompt

Cantrip is invoked through `--no-tui --yolo` with the prompt piped via stdin so the run is unattended through to the design proposal.  The full prompt is in [`demos/recordings/hero-ntfy.sh`](recordings/hero-ntfy.sh); the gist:

```text
I want a production-quality charm for ntfy, the self-hosted push
notification server (https://github.com/binwiederhier/ntfy v2.19.2).

Workflow guidance:
- Use the FULL research → design → build → deploy → test flow.
- This is NOT a sprint build.  Do NOT take the sprint path.
- When you call plan_tasks, do NOT pass `charm_type`.  Let the
  planner go through the research phase so the design is grounded
  in upstream sources.

The charm must include: ops-tracing, full COS observability
(Prometheus scrape, Loki logs, Grafana dashboards, Tempo traces),
persistent storage for the cache and attachments, ingress with
behind-proxy support, Scenario unit tests, and Jubilant integration
tests.  Charm name: ntfy.
```

The phase-naming nudge is load-bearing: without it, Cantrip's planner sees `charm_name="ntfy"` + an inferred `charm_type="k8s"` and routes through sprint mode, which deliberately skips tests and observability.  The marketing demo wants the full path.

## What the recording shows

The cast walks through the autonomous research path that opens every full-path Cantrip build:

1. **Preflight** — Cantrip checks Concierge, the Juju CLI, the controller, and the COS model.  Each tick lands as a green ✓ in the cast.
2. **Research** — three subagents run in parallel: a web-doc sweep of the ntfy operator manual, a Charmhub survey for any prior charm, and (when the planner sees a `source_url`) a source-repo analysis.  A fourth synthesis subagent reads the outputs and drafts a design document.
3. **Design proposal** — Cantrip prints the synthesised design (substrate choice, relations, config options, COS plan, test strategy) and surfaces a CONFIRM task for operator review.  The cast ends naturally at this point — stdin closes, the CLI exits cleanly.

The follow-on phases — build, deploy, test — produce the final charm with ops-tracing, full COS observability, Scenario unit tests, and Jubilant integration tests.  Today they're driven from the TUI: open `cantrip run ~/ntfy-charm` against the same directory, the agent picks up the saved session, and the operator approves the pending CONFIRM task to release the build queue.

## Verifying the artefact

Once the build completes, the resulting charm under `~/ntfy-charm/` can be scored against the gold rubric:

```bash
uv run pytest tests/eval -k ntfy -q
```

…or audited piecemeal with the standalone `charmlint`:

```bash
uv run charmlint --no-colour ~/ntfy-charm
```

The marketing-site embed of the cast highlights the timing markers for each phase so a viewer can jump straight to "research" or "test" without watching the full 5 minutes.

## Re-recording

```bash
# 1. Reset the target.
rm -rf ~/ntfy-charm && mkdir ~/ntfy-charm

# 2. Run the long capture (foreground or background).
demos/recordings/hero-ntfy.sh

# 3. Speed the raw cast up to 5 minutes (factor 6 from a 30-minute run).
demos/recordings/_speedup.py demos/recordings/hero-ntfy.cast \
    demos/recordings/hero-ntfy-5min.cast --factor 6
```

The speedup is non-destructive — `_speedup.py` only writes to its output path, so the raw cast stays around for re-edits or a different speed.
