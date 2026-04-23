---
title: "How to choose an LLM provider — Cantrip"
description: "Select the right LLM provider for Cantrip: Gemini, Claude, or local inference snaps."
h1: "Choose an LLM provider"
subtitle: "Cantrip supports three LLM providers. This guide helps you pick the right one for your situation."
section: howto
breadcrumb_label: "Choose an LLM provider"
see_also:
  - label: "CLI reference"
    href: "reference-cli.html"
  - label: "Configure light models"
    href: "howto-light-models.html"
---

{#overview}
## Provider comparison

| Provider | API key needed | Best for | Cost |
|---|---|---|---|
| **Gemini** (default) | Yes (`GEMINI_API_KEY`) | General use, generous free tier | Free tier available |
| **Claude** | Yes (`ANTHROPIC_API_KEY`) | Best output quality, complex charms | Paid |
| **Inference snap** | No | Air-gapped environments, privacy | Free (local GPU) |

{#gemini}
## Use Gemini (default)

Gemini is the default provider. Get an API key from
[Google AI Studio](https://aistudio.google.com/app/apikey),
then:

<pre><code><span class="prompt">$</span> export GEMINI_API_KEY="your-key-here"
<span class="prompt">$</span> cantrip</code></pre>

To use a specific Gemini model:

<pre><code><span class="prompt">$</span> cantrip --model gemini-2.5-pro</code></pre>

{#claude}
## Use Claude

Claude often produces higher-quality charm code, especially for complex
infrastructure charms (Path C). Get a key from the
[Anthropic console](https://console.anthropic.com/):

<pre><code><span class="prompt">$</span> export ANTHROPIC_API_KEY="your-key-here"
<span class="prompt">$</span> cantrip --provider claude</code></pre>

To specify a model:

<pre><code><span class="prompt">$</span> cantrip --provider claude --model claude-sonnet-4-6</code></pre>

{#inference-snap}
## Use local inference snaps

Ubuntu inference snaps run models locally on your GPU with no API key
or internet connection required. Install the snap first:

<pre><code><span class="prompt">$</span> sudo snap install gemma3
<span class="prompt">$</span> cantrip --provider inference-snap --snap gemma3</code></pre>

Other supported snaps include `nemotron-3-nano` for lighter
workloads. The quality of output depends on your GPU and the model
size.

<div class="callout-warn callout">
  <p>
    Local models produce lower-quality output than cloud APIs,
    particularly for complex charm paths. Consider using a cloud
    provider for the primary model and a local model for
    <a href="howto-light-models.html">light tasks</a>.
  </p>
</div>

{#hybrid}
## Hybrid setups

You can combine providers — use a powerful cloud model for code
generation and a local model for internal tasks like research
summarisation and log queries:

<pre><code><span class="prompt">$</span> cantrip --provider claude \
    --light-provider inference-snap --light-snap nemotron-3-nano</code></pre>

See [Configure light models](howto-light-models.html) for
full details on cost routing.
