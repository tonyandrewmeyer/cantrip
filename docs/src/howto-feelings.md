---
title: "How to convene the inner parliament — Cantrip"
description: "Run emotion subagents over your charm to surface delight, friction, risk, taste, and empathy suggestions."
h1: "Convene the inner parliament"
subtitle: "Run five emotion subagents over your charm to surface suggestions through distinct review lenses: delight, risk, friction, taste, and empathy."
section: howto
breadcrumb_label: "Convene the inner parliament"
see_also:
  - label: "Emotion subagents"
    href: "explanation-emotions.html"
  - label: "Configure light models"
    href: "howto-light-models.html"
---

<div class="callout-warn callout">
  <p>
    <strong>Experimental.</strong> The inner parliament is a
    proof-of-concept feature. The personalities may produce generic
    or theatrical output on some charms; treat the suggestions as
    prompts for thought, not a finished checklist. See
    <a href="explanation-emotions.html">Emotion subagents</a> for
    the design rationale and known limits.
  </p>
</div>

{#what-it-does}
## What it does

The `/feelings` command assembles a small snapshot of
your charm (identity, recent decisions, key files) and sends it in
parallel to one or more **emotion subagents**. Each
emotion reviews through its own lens and returns 1–3
structured suggestions. The results are merged into a single
markdown report posted back to the chat.

The emotions run on the light model, do not use tools, and do not
modify your charm or the work queue. The output is purely
advisory — you decide what (if anything) to act on.

{#run-it}
## Run it

Type the command in the chat input:

<pre><code><span class="prompt">&gt;</span> /feelings</code></pre>

With no arguments, the default pair runs: **Joy** and
**Fear**. These are the two most differentiated
lenses (delight vs risk), so they give the most signal per call.

A short system message announces the run; the report appears when
all enabled emotions have responded (usually a few seconds).

{#choose-emotions}
## Choose which emotions to run

Pass one or more emotion names as arguments to override the
default pair:

<pre><code><span class="prompt">&gt;</span> /feelings anger disgust
<span class="prompt">&gt;</span> /feelings joy fear anger disgust sadness</code></pre>

The full cast is:

| Emotion | Lens | Useful when |
|---|---|---|
| **joy** | Delight, first-run experience, nice touches | You have a working charm and want polish ideas |
| **fear** | Security holes, failure modes, hardening | Before shipping, or before a compliance review |
| **anger** | User-visible friction and papercuts | You suspect the operator experience is rough |
| **disgust** | Code taste, inconsistency, tech debt | Before a PR, or during a refactor pass |
| **sadness** | Graceful degradation, lonely error paths | When the unhappy paths feel under-tested |

Unknown names are rejected with a message listing the valid
emotions — nothing runs until the input is valid.

{#read-the-report}
## Read the report

The report is grouped by emotion, in the order you requested them.
Each suggestion has four fields:

- **Title** — a short imperative headline
  (“Add a backup action”).
- **Severity** — `high`,
  `medium`, or `low`, as judged by the
  emotion. Cross-emotion severity is not directly comparable
  (Fear's “high” means “this could break
  in production”; Joy's “high” means
  “a large missed opportunity for delight”).
- **Rationale** — one or two sentences
  explaining why the emotion feels this way.
- **Suggested change** — a concrete,
  actionable edit.

If an emotion's response could not be parsed or the provider
errored, its name is noted at the end of the report. The other
emotions are unaffected — partial parliaments are fine.

{#apply-suggestions}
## Apply the suggestions

The parliament does not write to the work queue or modify files.
To act on a suggestion, paste it back into the chat as a normal
request:

<pre><code><span class="prompt">&gt;</span> add a backup action that runs `redis-cli BGSAVE`
<span class="prompt">&gt;</span> move the admin password from config to a Juju secret</code></pre>

The agent then picks it up like any other user request —
planning, confirmation, and execution flow normally.

{#when-to-run}
## When to run it

- **Before asking for a PR** — run
  `/feelings disgust fear` for a taste-and-risk pass.
- **After a design proposal is approved** —
  run `/feelings joy fear` to catch delight
  opportunities and risks before the build starts.
- **Mid-build, when you feel stuck** — the
  personalities can surface concerns the main agent skipped.
- **Before shipping** — run the full cast
  (`/feelings joy fear anger disgust sadness`) for
  one last pass.

{#cost}
## Cost

Each enabled emotion is one LLM call on the light provider, with
no tool rounds. A default `/feelings` invocation costs
two light-model requests. Running the full cast costs five. See
[Configure light models](howto-light-models.html) for
how to route these to a cheap or local model.

{#turn-off}
## Turn it off

The command is triggered only when you type it — there is
no automatic invocation. Simply do not run `/feelings`
and the parliament never meets.

If you want to keep the feature disabled project-wide, the
command is a single guard in the TUI (`src/cantrip/tui/app.py`);
removing that block disables it entirely.
