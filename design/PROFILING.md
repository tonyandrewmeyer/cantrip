# Profiling and SLOs — Research Findings

> Output of Phase 87.3.  This is a research document, not a design.
> It records the question (should Cantrip grow first-class support
> for SLO management and continuous profiling?), the agent's role for
> each, the tool/skill split, and the verdict — including whether
> profiling work belongs to Phase 87 or to a standalone Phase 89+.

## TL;DR

- **Sloth (SLO management) is skill-shaped, not tool-shaped.**
  The agent's role is *generation at deploy time*: when a user adds
  observability to a charm, the agent should also propose a small,
  sensible SLO bundle (hook-success ratio, p95 hook duration,
  workload-availability SLO).  This is a one-shot YAML generation
  task that fits as a subsection of
  ``src/cantrip/skills/observability/SKILL.md``.  The
  ``charmlibs-interfaces-sloth`` PyPI package
  (already documented in ``design/UPSTREAM_AUDIT.md``) gives the
  relation-interface schema; the workload story is "expose the SLO
  YAML the charm computed, let Sloth render Prometheus rules."
- **Parca / Pyroscope (continuous profiling) is tool-shaped, but
  speculative today.**  The natural shape mirrors
  ``TempoWaterfallTool`` (``agent/tools/observability.py:1111``):
  fetch a flame-graph snapshot, render it to PNG, return image +
  summary caption (top-N hot paths).  But charms are
  *event-driven*, not throughput-driven — profiling is rarely the
  bottleneck.  Building a tool before a real "charm pegging CPU
  during hook execution" case appears would be speculative.
- **Verdict: split the work.**  *Sloth* lands as a Phase 87
  follow-up — a small skill expansion alongside the Alertmanager
  / Catalogue work in 87.1 / 87.2.  *Profiling* defers to a
  standalone **Phase 89** opened against three named triggers
  (§5).  This lets Phase 87 close on its observability-coverage
  promise without dragging the speculative profiler-data work
  along.

The rest of this document walks the evidence.

## 1. Sloth — what it is and how charms use it

### 1.1 What Sloth is

[Sloth](https://sloth.dev/) is a Prometheus-rule generator for SLOs.
The user writes a small YAML document describing the SLI
(Service Level Indicator — typically a Prometheus metric expression),
the SLO targets (e.g. "99.5% over 30 days"), and Sloth emits the
Prometheus recording / alert rules that compute the burn rate, error
budget, and multi-window alerts.  The user-facing input is small;
the output is verbose.

The Charmhub side is a charm that runs Sloth as a service in the
COS model and exposes its rule generator to other charms via a
relation interface.  The corresponding PyPI library is
``charmlibs-interfaces-sloth`` — its publication on PyPI was the
key finding in ``design/UPSTREAM_AUDIT.md`` (the previous LIB001
mapping that listed it as ``sloth-lib`` was wrong).

### 1.2 What "the agent's role" is

Two candidate roles.  Only one fits.

| Role | What it would mean | Fit |
|---|---|---|
| **Generate SLO YAML at deploy time** | When the user adds observability to a charm, the agent also drops a small ``slos.yaml`` covering the obvious indicators (hook success rate, p95 hook duration, workload availability) | **Right fit** — generation is one-shot, low-frequency, and the agent already understands the charm's hooks, workload type, and metrics endpoint |
| **Audit existing SLOs** | Read a charm's existing ``slos.yaml``, flag missing indicators, suggest additions | **Wrong fit** — would require domain-specific SLO knowledge, the audit work overlaps Sloth's own validators, and few charms ship SLOs to audit today |

The "generate at deploy time" role is the one that uses the
information the agent already has.  No new tool is needed — the
agent uses ``write_file`` to drop the YAML alongside the charm's
existing observability wiring.

### 1.3 The integration surface

A charm that wants to be SLO-managed by Sloth:

1. Adds the Sloth relation to ``charmcraft.yaml`` (interface
   ``slos`` or whatever the upstream charm exposes — the
   ``charmlibs-interfaces-sloth`` schema is the source of truth).
2. Drops a ``slos.yaml`` (or equivalent CharmConfig) describing
   the SLOs the charm wants Sloth to manage.
3. Sends the SLO definition over the relation when the relation
   joins.  Sloth synthesises the Prometheus rules and pushes
   them into the COS model's Prometheus.

The first two are charm-author work; the third is library code
inside the relation handler.  All three fit cleanly into the
"add observability" skill expansion already covered by
``observability/SKILL.md``.

### 1.4 Sloth-the-skill content

What a Sloth subsection in ``observability/SKILL.md`` would carry:

- Default SLOs for charm-of-X workloads (example: a 12-factor app
  gets HTTP-availability + p95-latency; an infrastructure charm
  gets hook-success-rate + p95-hook-duration; a custom app gets
  the same workload-availability SLOs the user can tune).
- The ``charmcraft.yaml`` relation block with the right interface
  name.
- The ``slos.yaml`` skeleton with placeholders for SLI
  expressions, SLO targets, and burn-rate alert thresholds.
- Charmlib import shape (``from charmlibs.interfaces import
  sloth``) and the typical relation-handler stub.
- Integration with the existing Prometheus subsection — the SLOs
  reference metrics already exposed via the ``metrics-endpoint``
  relation, so the two sections compose.

Sized: ~50 lines of skill markdown plus a worked-example
``slos.yaml``.  Cost: 1-2 hours, same shape as the Alertmanager
expansion in 87.1.

## 2. Parca and Pyroscope — what they are and the agent's role

### 2.1 What they are

Both are continuous-profiling backends.

- **[Parca](https://www.parca.dev/)** — eBPF-based profiler;
  Apache-2.0; pprof-format wire protocol; ships a charm on
  Charmhub.
- **[Pyroscope](https://grafana.com/oss/pyroscope/)** — Grafana
  Labs' continuous profiler; merged into the Grafana stack in
  2023; pprof-compatible; designed to slot alongside Loki / Tempo
  in a Grafana deployment.

Both consume long-running profile data (typically eBPF samples
collected from the workload) and serve flame graphs over HTTP /
Grafana plugin.  The output is dense — a flame graph for a
five-minute sample can have thousands of stack frames.

### 2.2 The agent's role candidates

| Role | What it would mean | Fit |
|---|---|---|
| **Live profile reading** | Agent fetches a flame graph for a charm whose hook execution exceeds an SLO, identifies the top hot paths, suggests fixes | Right *shape*, wrong *frequency* — would fire only when an SLO breaches |
| **Continuous profiling at deploy time** | Wire profiling into the charm by default (sidecar, eBPF agent) so the data is there if needed | Wrong fit — most charms don't need it; the cost (sidecar memory, eBPF capability requirements) outweighs the benefit |
| **Profile-aware acceptance test** | Phase 17 acceptance harness asserts "no hook above N seconds at p95" against profile data | Possible but speculative — Phase 17 already asserts hook timing via Juju, the profiler view doesn't add new information for the cases tested |

Only the first role survives a "what does this enable that we
can't do today?" filter.  The other two duplicate work the
existing observability stack already covers (hook timing via
Tempo + Prometheus, deployment health via Juju status).

### 2.3 The natural tool shape

If profiling were shipped, the tool would mirror
``TempoWaterfallTool``:

```
flame_graph_query(workload_name, time_window, cos_model="cos")
  → fetch pprof from Parca/Pyroscope via the COS unit
  → flatten the call tree, identify top-N hot paths
  → render to PNG via Pillow (same renderer pattern as
    tempo_waterfall, but tree layout instead of waterfall)
  → return ToolResult(images=[...], caption="<top-3 hot paths>",
                      output="<text summary>")
```

The text caption would name the top-3 hot paths by self-time,
the cumulative percentages, and the file:function:line tuple.
The PNG attaches via the existing
``ToolResult.images`` (Phase 48).  No new abstractions; the
``_find_cos_unit`` helper already used by Tempo / Loki / Grafana
extends to Parca/Pyroscope unchanged.

Sized: ~250-350 LOC + tests + Pillow renderer + caption
extraction.  Cost: 2-3 days, same shape as 1111-1547 in
``observability.py`` for the Tempo waterfall.

### 2.4 Why "speculative today"

Charm hooks rarely peg CPU.  The dominant slow-charm shapes
this tool would help with are:

1. **A tight loop in a relation handler** — usually visible from
   hook timing alone (Prometheus + Tempo).
2. **A slow library call** (e.g. a charm-lib that walks the
   workload's filesystem) — visible from Tempo span timing.
3. **A workload that pegs CPU on its own** — that's the
   workload's profiling story, not the charm's.

In each case the *current* observability stack already surfaces
the signal at a granularity the agent can act on.  A flame
graph adds detail the agent rarely needs.  Building the tool
before a charm-debug case demonstrates the gap is speculative
— the same anti-pattern Phase 39 (ACP research) called out:
"Don't build speculatively; revisit when a concrete trigger
appears."

## 3. Tool / skill split

| Subsystem | Skill content | Tool? | Comment |
|---|---|---|---|
| Sloth | Yes (subsection in ``observability/SKILL.md``) | No | Generation-time work; existing ``write_file`` + ``charmcraft.yaml`` editing tools cover it |
| Parca | No (defer) | No (defer) | Speculative; tool sketch in §2.3 if a trigger fires |
| Pyroscope | No (defer) | No (defer) | Same as Parca; pick one (probably Pyroscope, given Grafana-stack alignment) when a trigger fires |

The split mirrors the same logic as Phase 86: skill expansion
ships *generation knowledge* the agent needs today; typed tools
ship *autonomy* the agent doesn't need yet.

## 4. Phase placement — 87 follow-up vs Phase 89+

The phase prompt asked: "whether profiling is a Phase 87
follow-up or a standalone Phase 89+."

| Workstream | Phase placement | Rationale |
|---|---|---|
| Sloth skill subsection | **Phase 87 follow-up** (alongside 87.1 + 87.2) | Same shape as the Alertmanager / Catalogue expansions; same observability-coverage exit criterion |
| Parca / Pyroscope tool | **Standalone Phase 89** | Different size class (typed tool + Pillow renderer + Tempo-pattern reuse); different trigger surface (charm performance, not deploy-time integration); deserves its own phase prompt and exit criteria |

Phase 87 closes when Alertmanager + Catalogue + Sloth all have
skill-level coverage matching the Prometheus / Grafana baseline.
The Sloth bullet adds itself to that exit criterion.

Phase 89 opens (when triggered) with §2.3's tool sketch as the
deliverable, ``TempoWaterfallTool`` (``observability.py:1111``)
as the architectural template, and the charm-performance trigger
that opened it as the exit-criteria gate ("the original charm's
profile reads cleanly via the new tool").

## 5. Revisit triggers

### Phase 87 (Sloth skill) — opens immediately

The Sloth subsection lands alongside the Alertmanager (87.1) and
Catalogue (87.2) expansions.  No further trigger needed; this
phase scopes it as Phase **87.4 — Sloth skill subsection** in
the ROADMAP entry below.

### Phase 89 (Parca / Pyroscope tooling) — opens when *any* of:

1. **Charm-performance debug case.**  A charm in a real session
   shows hook timings the agent can't explain from Tempo +
   Prometheus alone, and the user wants the agent to reach for
   a profiler view rather than escalate.
2. **SLO-breach response.**  Phase 87.4 ships and an SLO
   *actually* breaches in a deployed charm; the natural next
   step from "alert fires" is "show me where the time went."
3. **A user asks for it.**  The smallest possible trigger:
   someone with a slow charm wants the agent to act on profile
   data, not just describe it.
4. **Pyroscope/Parca becomes the default profiler in COS.**  If
   the canonical observability stack adopts one as a
   first-class component (the way Tempo became the default
   trace store), the integration story crosses from "speculative"
   to "expected."

When 1-3 fire, the implementation phase opens with §2.3's tool
sketch as the deliverable scope.  When 4 fires, the work
broadens to "default-on" — possibly with a charm scaffolding
change in ``charmcraft_init`` that wires the agent automatically.

## 6. What this phase is *not*

- **Not a commitment to ship Parca/Pyroscope tooling.**  The
  Phase 89 trigger list is real, not a soft gate; the tool work
  doesn't start until a trigger fires.
- **Not a rewrite of the existing observability skill.**  Sloth
  joins the skill as a subsection at parity with the other COS
  components; Prometheus / Grafana / Loki / Tempo / Traefik
  sections stay untouched.
- **Not an SLO-audit story.**  Generation only; auditing existing
  SLOs is a different feature with a different cost / value
  profile.
- **Not a workload profiling story.**  Cantrip builds *charms*; a
  charm's workload doing its own profiling is the workload's
  business.  This phase only covers profiling the *charm code*
  (hook execution, relation handlers, library calls).
