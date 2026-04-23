---
title: "How to configure light models — Cantrip"
description: "Route internal tasks to cheaper LLM models to reduce cost without sacrificing charm quality."
h1: "Configure light models"
subtitle: "Use cheaper models for internal tasks to reduce cost while keeping the primary model for code generation."
section: howto
breadcrumb_label: "Configure light models"
see_also:
  - label: "Choose an LLM provider"
    href: "howto-provider.html"
  - label: "How Cantrip works"
    href: "explanation-architecture.html"
---

{#how-it-works}
## How cost routing works

Cantrip categorises tasks by how much model capability they need:

| Task type | Model used | Examples |
|---|---|---|
| Code generation | Primary | Writing charm code, designing integrations |
| Research | Light | Summarising docs, web search analysis |
| Test aggregation | Light | Parsing test output, deciding pass/fail |
| Log queries | Light | Analysing Loki logs, Tempo traces |
| Context compaction | Light | Summarising long conversations |

{#same-provider}
## Light model from the same provider

The simplest setup uses a cheaper model from the same provider:

<pre><code><span class="prompt">$</span> cantrip --provider gemini --light-model gemini-2.0-flash</code></pre>

Or with Claude:

<pre><code><span class="prompt">$</span> cantrip --provider claude --light-model claude-haiku-4-5</code></pre>

{#different-provider}
## Light model from a different provider

For maximum cost savings, use a local inference snap for light tasks
while keeping a cloud model for the primary work:

<pre><code><span class="prompt">$</span> cantrip --provider claude \
    --light-provider inference-snap \
    --light-snap nemotron-3-nano</code></pre>

This sends code generation to Claude but runs research, compaction,
and log analysis locally with no API cost.

{#auto}
## Automatic detection

If you omit `--light-model`, Cantrip automatically selects
a lighter model from the same provider when one is available. You
only need to configure it explicitly when you want to override the
default choice or use a different provider.
