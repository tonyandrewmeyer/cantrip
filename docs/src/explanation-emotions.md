---
title: "Emotion subagents — Cantrip"
description: "Why Cantrip has five personality-driven review subagents, how they're scoped to avoid overlap, and the tradeoffs involved."
h1: "Emotion subagents"
subtitle: "Five personality-driven review lenses — Joy, Fear, Anger, Disgust, Sadness — each reviewing your charm through a distinct prompt. A small, deliberately odd experiment in structured second opinions."
section: explanation
breadcrumb_label: "Emotion subagents"
on_this_page:
  - { anchor: "why-lenses", label: "Why different lenses" }
  - { anchor: "the-cast", label: "The cast of five" }
  - { anchor: "scope", label: "Scope boundaries" }
  - { anchor: "how-it-runs", label: "How a parliament runs" }
  - { anchor: "tradeoffs", label: "Tradeoffs" }
  - { anchor: "experimental", label: "Experimental status" }
---

<div class="callout-warn callout">
  <p>
    <strong>Experimental.</strong> This feature is a proof of
    concept. It may produce generic or theatrical output; the
    design may change or be removed entirely based on experience.
    See <a href="howto-feelings.html">Convene the inner
    parliament</a> for the how-to.
  </p>
</div>

{#why-lenses}
## Why different lenses

A monolithic reviewer — one LLM prompt asked to “spot
everything wrong with this charm” — tends to produce
a flattened average: a handful of bland, catch-all suggestions
that skim every concern without committing to any. Large models
are especially prone to this when a single prompt pulls them in
many directions at once.

The inner parliament takes the opposite approach: **split
the review into narrow lenses, each with a strong prior**.
A prompt that exists only to spot security risks commits to
security. A prompt that exists only to find papercuts commits to
papercuts. The cost is some duplication across lenses; the
benefit is that each lens produces something sharper than a
generalist would.

Personality framing is the carrier. “You are Fear” is
a compact way to encode a review prior that “focus only on
security and failure modes” describes less memorably. The
framing also makes the output read as opinion rather than
adjudication — a useful tone for a feature whose output is
advisory.

{#the-cast}
## The cast of five

The five emotions are borrowed from Pixar's *Inside
Out*, and chosen for coverage rather than narrative
completeness. Together they span the dimensions a thorough
reviewer would visit:

| Emotion | Review dimension | What it sounds like |
|---|---|---|
| **Joy** | Delight — what could spark joy? | “A `dump-status` action would save the operator a chore.” |
| **Fear** | Risk — what could go wrong? | “The admin password is stored in plaintext config; use a Juju secret.” |
| **Anger** | Friction — what will annoy the operator? | “The `reload` action has no progress output; it looks hung.” |
| **Disgust** | Taste — what looks ugly? | “Four files mix snake_case and camelCase; pick one.” |
| **Sadness** | Empathy — what happens in the unloved cases? | “Missing relation throws a traceback; a `BlockedStatus` with a clear message would be kinder.” |

Joy and Anger form one axis (delight vs friction, both
user-facing). Fear and Sadness form another (preventing failure
vs handling it gracefully). Disgust is a distinct axis: code
taste, not user experience. The default pair when you run
`/feelings` with no arguments is Joy and Fear,
chosen as the most differentiated across axes.

{#scope}
## Scope boundaries

The biggest risk with a parliament is overlap: five prompts all
pointing at the same concerns, each adding only noise. The
prompts defend against this explicitly.

- **Anger ≠ Disgust.** Anger covers
  *user-visible* friction (bad error messages, cryptic
  actions, slow feedback). Disgust covers *code*
  aesthetics (dead code, Harness-style tests, inconsistent
  naming). A confusing action name is Anger's problem; a
  messy function body is Disgust's.
- **Fear ≠ Sadness.** Fear wants to
  *prevent* failures (add TLS, validate inputs, require
  auth). Sadness wants failures to be *gentle* when they
  happen (meaningful `BlockedStatus`, graceful
  degradation on missing relations, a clean teardown path). The
  same incident can provoke both, but from different angles.
- **Joy stays positive.** Joy ignores problems
  entirely. Its job is to name the missing treat, not to
  double-count concerns that other emotions already cover.

{#how-it-runs}
## How a parliament runs

Running `/feelings` in the TUI triggers a small
pipeline:

1. The requested emotion names are validated against the known
   cast. Unknown names reject the command with a list of valid
   options.
2. A **context snapshot** is assembled from
   `AgentState`: charm name, type, framework, recent
   decisions, and the contents of up to six key files
   (`charmcraft.yaml`, `metadata.yaml`,
   `config.yaml`, `actions.yaml`,
   `README.md`, `src/charm.py`) if they are
   present and under a small size limit.
3. Each enabled emotion is launched in parallel as a single LLM
   call on the [light
   provider](howto-light-models.html), with the emotion's prompt as the system
   message and the snapshot as the user message. No tools are
   offered, so each call is one request and one response.
4. Each response is parsed as a JSON array of suggestion objects.
   Responses that cannot be parsed, or whose provider call
   errored, are recorded as *failed emotions*; they do
   not fail the whole run.
5. The surviving suggestions are grouped by emotion, formatted as
   markdown, and posted back to the chat as a system message. The
   main agent's conversation state is not touched.

The emotions never call tools, never write files, and never add
work-queue tasks. This is a deliberate constraint — a
parliament should be a mirror, not a builder.

{#tradeoffs}
## Tradeoffs

Several tensions shape the design. None are fully resolved.

### Theatrics versus substance

Personality framing can produce prose that sounds evocative but
says little (“I worry that the charm feels cold to a new
user”). The prompts push back by requiring a JSON output
with a concrete `suggested_change` field — no
suggestion is valid without a named edit. In practice,
suggestions are only as useful as the model behind them; a
weaker light model is more likely to drift into theatre.

### Coverage versus cost

Five LLM calls per invocation is more expensive than one. The
light provider mitigates this: the parliament uses the cheap
model, not the primary. Running the default pair
(`joy` + `fear`) is two light-model calls
— cheaper than many of Cantrip's routine subagents
and comparable to a single compaction pass.

### Independence versus agreement

The emotions do not talk to each other. They cannot debate or
reach a verdict. That keeps the design simple and preserves each
lens' distinctness, but it means the user is the
aggregator: two emotions pointing at similar things is a signal
to take seriously; a single emotion's suggestion may or may
not be worth acting on. A future version could add a moderator
pass that de-duplicates and ranks, at the cost of another LLM
call and a risk of flattening back into monolithic review.

### Advisory versus actionable

The parliament does not write to the work queue. This is a
choice: premature automation would turn cute suggestions into
expensive side-effects. A user who wants to act on a suggestion
simply paraphrases it as a normal request and the main agent
handles it. This keeps the user's judgment in the loop.

{#experimental}
## Experimental status

The inner parliament ships as a proof of concept, not a
polished feature. Its future depends on whether, in practice,
the personality framing produces better suggestions than a plain
checklist would — or just the same suggestions, dressed up.
The feature may stay, change shape, or be removed. If you try
it, what you notice about the quality of the output is the
interesting data.
