---
title: "Best-of-N racing and Arena mode — Cantrip"
description: "Why Cantrip runs multiple models on the same task, how the scoring rubric ranks them, and how blind A/B Arena captures preferences."
h1: "Best-of-N racing and Arena mode"
subtitle: "Two ways to pit models against one another: an objective Best-of-N race scored by measurable charm quality, and a blind A/B <code>/arena</code> that captures human preference."
section: explanation
breadcrumb_label: "Racing and Arena"
on_this_page:
  - { anchor: "why-race", label: "Why race at all" }
  - { anchor: "two-mechanisms", label: "Two mechanisms" }
  - { anchor: "scoring", label: "The scoring rubric" }
  - { anchor: "signals", label: "What each signal measures" }
  - { anchor: "viability", label: "Viability and tie-breaking" }
  - { anchor: "config", label: "RaceConfig and cost gates" }
  - { anchor: "arena", label: "Blind A/B Arena" }
  - { anchor: "events", label: "Transcript events" }
  - { anchor: "limits", label: "Current limits" }
---

<div class="callout-warn callout">
  <p>
    <strong>Library-only surface for objective racing.</strong>
    <code>/arena</code> is fully user-facing, but the Best-of-N
    race coordinator is wired into the executor behind a
    <code>RaceConfig</code> that has no CLI flag or environment
    variable yet. Racing runs only when a caller constructs an
    executor with a non-default config &mdash; see
    <a href="#limits">Current limits</a>. This page documents the
    design so you can read race events in transcripts and anticipate
    the surface when it lands.
  </p>
</div>

{#why-race}
## Why race at all

Charm building has an unusually clean success signal. A generated
charm can be packed, linted with [charmlint](explanation-charmlint-rs.html),
unit-tested, and scored against an operational-readiness
checklist. Unlike open-ended writing tasks, the output is
*measurable*: a charm with zero charmlint errors and 95 %
readiness is objectively better than one with six errors and
60 % readiness, regardless of how either got there.

Given a measurable output and an embarrassingly parallel work
pattern (each candidate runs in its own git worktree — see
[How Cantrip works](explanation-architecture.html)),
running several models on the same task and picking the winner
is a natural fit. It also sidesteps the “which model is
best today” argument: you don’t have to choose in
advance if you race them and let the rubric decide.

{#two-mechanisms}
## Two mechanisms, same goal

Cantrip exposes two racing shapes. They share the name, but the
implementations and intended uses are distinct.

| | Best-of-N race | Blind A/B Arena |
|---|---|---|
| **Module** | `cantrip.agent.race` | `cantrip.agent.arena` |
| **Per candidate** | Full subagent loop with tools | Single provider completion, no tools |
| **Scope** | Per `TaskCategory` (BUILD, DESIGN, …) | One-off, user-triggered |
| **Winner** | Rubric score against charm outputs | You pick, blind to model names |
| **Outcome** | Winner’s worktree merged back | Preference written to global memory |
| **Trigger** | Automatic, per `RaceConfig` | `/arena <prompt>` |

{#scoring}
## The scoring rubric

Four signals combine into a single total in `[0.0, 1.0]`.
Weights sum to one so scores are directly comparable across a
pool, even when candidates happen to run different test counts
or produce different diff sizes.

| Signal | Weight | Why this weight |
|---|---|---|
| Charmlint violations (weighted by severity) | **30 %** | Errors are usually spec violations that break the charm |
| Operational-readiness percentage | **30 %** | Captures whether the charm has the moving parts a real operator needs |
| Unit-test pass ratio | **25 %** | High-signal but the other two lead for “shippable” |
| Diff size (smaller is better) | **15 %** | Tie-breaker that nudges toward focused changes |

Each signal is scored into `[0, 1]` independently, then
the total is a weighted sum. The constants all live in
`src/cantrip/agent/race.py`; tune them in one place
rather than scattering magic numbers.

{#signals}
## What each signal measures

### Charmlint — exponential decay on weighted violations

Each violation is weighted by severity: `error` × 3,
`warning` × 1, `info` × 0.1.
The weighted total feeds an exponential decay with a constant of
10, so a clean charm scores 1.0, one error drops to ~0.74, and
a charm with three errors and several warnings falls below 0.25.
Errors dominate because they block shipping; warnings are a
speed bump; infos are advisory.

The scorer calls the same
[charmlint tool](explanation-charmlint-rs.html) the
agent uses elsewhere, so the Rust-vs-Python backend selection
stays in one place. A tool failure degrades to zeroed counts
rather than crashing the race.

### Readiness — linear on the overall score

The operational-readiness tool produces an overall percentage
between 0 and 100. The scorer normalises it to `[0, 1]`.
When the tool can’t evaluate the directory (for example, no
`charmcraft.yaml`), the signal returns 0 rather than
0.5: a candidate that isn’t actually a charm should lose to
one that is. The readiness tool writes an
`OPERATIONAL_READINESS.md` report into the worktree as
a side effect — the scorer measures diff *before*
running readiness so the uncommitted report doesn’t inflate
diff-size counts.

### Tests — normalised pass ratio

The test signal is `passed / total` when any tests exist,
and 1.0 when none do — a candidate shouldn’t be
penalised for working in a test-free area. Integration test
counts are a follow-up; the current rubric scores unit tests
only. Baseline-aware scoring (“this candidate ran fewer
tests than the others; penalise it proportionally”) is not
yet implemented.

### Diff size — linear penalty, capped at 2000 lines

Smaller diffs score higher. The decay is linear up to a cap of
2000 lines; anything above the cap scores 0 for this signal.
A zero-line diff is suspicious (the candidate may have committed
nothing) and gets a middling 0.5 so charmlint and readiness
decide the winner rather than rewarding inaction.

The diff is taken against the worktree’s `base_sha`
via `git diff --numstat base_sha..HEAD`, so only
*committed* changes count. Binary files are skipped.
Git errors fall through to `(0, 0)` rather than
crashing — a broken measurement shouldn’t sink a race.

{#viability}
## Viability and tie-breaking

A candidate’s `ExitState` short-circuits the
rubric before subscores are combined:

- `COMPLETED` and `BLOCKED` are *viable*
  — blocked runs can still be worth merging if they produced
  partial progress while the user resolves the block.
- `FAILED` and `NOOP` force a total of
  `0.0` regardless of the other signals. A failed
  candidate with clean charmlint (because it never changed
  anything) is not a win.

Ties break on lower `diff_lines` (smaller change wins)
and then on lexicographic `candidate_id`, so repeated
races with the same pool produce the same winner when the
underlying measurements agree. A `is_perfect` threshold
of 0.999 exists as a hook for early cancellation
(`RaceConfig.cancel_on_perfect`), but early cancel
isn’t implemented yet — the coordinator waits for every
candidate.

{#config}
## RaceConfig and cost gates

`RaceConfig` is the opt-in surface. The default
disables racing entirely — `enabled_categories`
is an empty frozenset, so `should_race` always returns
False and the executor falls through to a single-subagent run.

<dl>
  <dt><code>enabled_categories</code> (default: empty)</dt>
  <dd>
    The <code>TaskCategory</code> values that are allowed to race.
    Typical values are <code>{BUILD, DESIGN}</code>: objectively
    measurable work where Best-of-N pays off.
  </dd>

  <dt><code>max_candidates</code> (default: 3)</dt>
  <dd>
    Upper bound on race width. <code>clamp_candidates</code>
    trims any pool larger than this. A setting of 0 or less
    disables racing even for enabled categories.
  </dd>

  <dt><code>budget_tokens</code> (default: 500 000)</dt>
  <dd>
    Hard cap on estimated total tokens. Races whose pre-run
    estimate exceeds this budget downgrade silently to a
    single-subagent run. Set to 0 or a negative value to disable
    the cap.
  </dd>

  <dt><code>confirm_threshold_tokens</code> (default: 200 000)</dt>
  <dd>
    Soft gate. Estimates above this threshold but below the
    hard budget surface a <code>CONFIRM</code> task so you can
    approve or decline the spend. Tuned so a two-way race on a
    typical BUILD task fires the gate but a cheap DESIGN race
    doesn&rsquo;t.
  </dd>

  <dt><code>baseline_tokens_per_run</code> (default: 75 000)</dt>
  <dd>
    Per-candidate token estimate used to multiply out the
    pre-race cost. Deliberately low so the CONFIRM gate fires
    early for racy tasks. Once streaming-usage aggregation lands
    (Phase 41.6), mid-flight accounting will replace this
    static estimate.
  </dd>

  <dt><code>cancel_on_perfect</code> (default: True)</dt>
  <dd>
    Reserved for early cancellation when a candidate hits the
    perfect-score threshold. Not yet implemented; the
    coordinator waits for every candidate today.
  </dd>
</dl>

### The three-way gate

At dispatch time the executor classifies every would-be race
into one of three outcomes:

| Outcome | Condition | What happens |
|---|---|---|
| `RACE` | Estimate ≤ `confirm_threshold_tokens` | Race runs silently |
| `CONFIRM` | Threshold &lt; estimate ≤ `budget_tokens` | A `CONFIRM` task gates the parent; reply *yes* or *no* |
| `DOWNGRADE` | Estimate &gt; `budget_tokens` *or* user declined | Falls through to a single-subagent run |

User decisions persist on the task (`task.race_decision`)
so a task that re-enters the executor for any reason is not
re-prompted. The CONFIRM task id is
`race-confirm-<parent-task-id>`; the executor
reuses an existing CONFIRM rather than creating duplicates.

{#arena}
## Blind A/B Arena

`/arena <prompt>` sends the same prompt to both
the primary and light providers concurrently, shuffles the two
replies into labels `A` and `B` (hiding
model names), and asks you to pick. Responses are capped at
2 000 tokens so the A/B block stays readable side-by-side.

Recognised replies are forgiving and case-insensitive:

- `A`, `pick A`, `left`
- `B`, `pick B`, `right`
- `tie`, `equal`, `both`, `neither`, `t`
- `skip`, `cancel`, `abort`, `never mind`

Unrecognised replies fall through to normal chat — you
aren’t locked out of talking to the agent while an arena is
pending. The TUI, CLI, and Web frontends all intercept pending
picks before routing the reply to the LLM.

Picks and ties write a `fact` memory at
`global` scope (so the preference carries across
charms), tagged `arena` and `model-preference`,
with `source="arena"` and a
`arena-preference-<8-hex>` title. The body
names both models and includes a 200-character excerpt of the
prompt so the preference is attributable to a specific ask.
`skip` clears the session without writing. See
[the memory how-to](howto-memory.html) for the
full memory model and
[the CLI reference](reference-cli.html#slash-commands)
for the exact command syntax.

Arena refuses to start when both sides would resolve to the
same `(provider, model)` pair — a blind A/B
against identical configurations produces no signal and wastes
tokens. It also requires a configured light provider
(`--light-provider` or
`CANTRIP_LIGHT_PROVIDER`).

{#events}
## Transcript events

Races and arenas emit structured events alongside the regular
task updates. They land in the session transcript so a reviewer
can reconstruct what happened after the fact.

<dl>
  <dt><code>race_confirm_requested</code></dt>
  <dd>
    Emitted when the soft gate fires. Payload carries
    <code>task_id</code>, <code>confirm_task_id</code>,
    <code>estimate_tokens</code>, <code>threshold_tokens</code>, and
    the candidate id list.
  </dd>

  <dt><code>race_downgraded</code></dt>
  <dd>
    Emitted when a would-be race runs as a single subagent
    instead. The <code>reason</code> field is either
    <code>over_budget</code> (hard cap) or <code>user_declined</code>
    (answered <em>no</em> to a CONFIRM). Over-budget downgrades
    include <code>estimate_tokens</code> and
    <code>budget_tokens</code> so you can see why.
  </dd>

  <dt><code>race_finished</code></dt>
  <dd>
    One row per race. Carries the winner&rsquo;s
    <code>candidate_id</code> and <code>score</code>, the candidate
    list, and <code>elapsed_s</code>. Empty winner fields mean every
    candidate failed.
  </dd>

  <dt><code>race_candidate</code></dt>
  <dd>
    One row per candidate, winner or loser. Includes the
    candidate&rsquo;s <code>exit_state</code>, <code>total</code> score,
    and <code>transcript_task_id</code>. The transcript task id is
    <code>&lt;parent_task_id&gt;__&lt;candidate_id&gt;</code>
    &mdash; join against <code>subagent_messages</code> on that key
    to read any loser&rsquo;s full tool-call trace, not just the
    winner&rsquo;s.
  </dd>
</dl>

{#limits}
## Current limits and planned work

- **No user-facing surface for `RaceConfig` yet.**
  The executor accepts a programmatic `RaceConfig`
  argument, but there are no CLI flags or environment variables
  to set `enabled_categories` and friends. Racing is
  reachable today through the Python API only; a proper surface
  lands with the next iteration of Phase 47.
- **No early cancellation.**
  `cancel_on_perfect` is a config knob but the
  coordinator waits for every candidate before scoring. A
  perfect score doesn’t short-circuit the others yet.
- **Static cost estimate.**
  `baseline_tokens_per_run` is a rough guess, not
  measured usage. Mid-flight budget accounting (“cancel
  once we’ve burned through the budget”) is deferred
  until streaming-usage aggregation lands in Phase 41.6.
- **Unit tests only.** The test subscore measures
  unit-test pass/total. Integration test counts are not yet
  surfaced to the rubric.

See also:

- [CLI reference — slash commands](reference-cli.html#slash-commands)
- [Using durable memory](howto-memory.html)
- [Charmlint Rust backend](explanation-charmlint-rs.html)
- [How Cantrip works](explanation-architecture.html)
