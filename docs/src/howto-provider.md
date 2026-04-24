---
title: "How to choose an LLM provider — Cantrip"
description: "Select the right LLM provider for Cantrip: inference snaps, Gemini, Claude, Fireworks.ai, OpenRouter, or any OpenAI-compatible endpoint."
h1: "Choose an LLM provider"
subtitle: "Cantrip supports six LLM providers. This guide helps you pick the right one for your situation."
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
| **Inference snap** | No | Air-gapped environments, privacy, Canonical-native stack | Free (local GPU) |
| **Gemini** (default) | Yes (`GEMINI_API_KEY`) | General use, generous free tier | Free tier available |
| **Claude** | Yes (`ANTHROPIC_API_KEY`) | Best output quality, complex charms | Paid |
| **Fireworks.ai** | Yes (`FIREWORKS_API_KEY`) | Open-weights models (Kimi, GLM, DeepSeek) with tool use | Paid |
| **OpenRouter** | Yes (`OPENROUTER_API_KEY`) | Meta-gateway to GPT, Claude, Llama, Grok, Mistral, … through one key | Paid |
| **OpenAI-compatible** | Yes (`OPENAI_COMPATIBLE_API_KEY`) | Any other OpenAI-compatible endpoint (Together, Groq, vLLM, …) | Depends |

{#inference-snap}
## Use local inference snaps

Ubuntu inference snaps are the Canonical-native path: a production-grade
OpenAI-compatible server, installed from the Snap Store, running models
locally on your GPU with no API key or internet connection required.
Install the snap first:

<pre><code><span class="prompt">$</span> sudo snap install gemma3
<span class="prompt">$</span> cantrip --provider inference-snap --snap gemma3</code></pre>

Other supported snaps include `nemotron-3-nano` for lighter
workloads and `qwen-vl` for vision tasks. The quality of output
depends on your GPU and the model size.

<div class="callout-warn callout">
  <p>
    Local models produce lower-quality output than cloud APIs,
    particularly for complex charm paths. Consider using a cloud
    provider for the primary model and a local model for
    <a href="howto-light-models.html">light tasks</a>.
  </p>
</div>

{#gemini}
## Use Gemini (default)

Gemini is the default cloud provider. Get an API key from
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

{#fireworks}
## Use Fireworks.ai

Fireworks hosts strong open-weights models — Kimi K2 (agentic/coding),
GLM, MiniMax, DeepSeek — behind an OpenAI-compatible API. Get a key
from your [Fireworks account](https://fireworks.ai/account/api-keys),
then:

<pre><code><span class="prompt">$</span> export FIREWORKS_API_KEY="your-key-here"
<span class="prompt">$</span> cantrip --provider fireworks</code></pre>

The default model is
`accounts/fireworks/models/kimi-k2p6`, a 256k-context
agentic model with native tool-use. Override with `--model`:

<pre><code><span class="prompt">$</span> cantrip --provider fireworks \
    --model accounts/fireworks/models/glm-5p1</code></pre>

Cantrip auto-detects the selected model's context window and
capability flags (tool use, vision) from the Fireworks
`/models` endpoint at startup.

<div class="callout-note callout">
  <p>
    Kimi K2 (and the DeepSeek-R1 and GLM reasoning variants)
    emits <code>reasoning_content</code> alongside the final
    reply, and the <em>reasoning tokens count against
    <code>max_tokens</code></em>. A low cap will be consumed
    entirely by reasoning and leave nothing for the answer — a
    prompt with <code>max_tokens=30</code> can come back with 30
    completion tokens and an empty response string.
  </p>
  <p>
    Cantrip surfaces the reasoning through the same
    <code>_thinking_content</code> metadata channel Claude uses
    for extended thinking, and honours
    <code>thinking_budget</code> on Fireworks by raising
    <code>max_tokens</code> to at least
    <code>thinking_budget&nbsp;+&nbsp;4096</code>. For manual
    testing, set <code>max_tokens</code> to at least 4&nbsp;096
    for simple prompts and 16&nbsp;000+ for tool-using turns.
  </p>
</div>

{#openrouter}
## Use OpenRouter

OpenRouter is a meta-gateway to hundreds of models — OpenAI GPT,
Anthropic Claude, Meta Llama, Mistral, Grok, DeepSeek — behind a
single OpenAI-compatible API and a single key. Useful when you
want a model Cantrip doesn't ship a dedicated provider for, or
when you want to A/B the same prompt across vendors.

Get a key from your [OpenRouter
keys page](https://openrouter.ai/settings/keys), then:

<pre><code><span class="prompt">$</span> export OPENROUTER_API_KEY="your-key-here"
<span class="prompt">$</span> cantrip --provider openrouter</code></pre>

The default model is `openai/gpt-4o` —
a long-lived choice that sits outside the coverage of Cantrip's
other providers. Override with any OpenRouter slug:

<pre><code><span class="prompt">$</span> cantrip --provider openrouter \
    --model meta-llama/llama-3.3-70b-instruct

<span class="prompt">$</span> cantrip --provider openrouter \
    --model x-ai/grok-4-fast</code></pre>

Cantrip auto-detects the selected model's context window, tool
support, and vision support from the OpenRouter
`/models` catalogue at startup, and sends
`HTTP-Referer` and `X-Title`
headers so Cantrip usage shows up on OpenRouter's public
ranking dashboards.

<div class="callout-note callout">
  <p>
    Prefer a dedicated provider when one exists — OpenRouter
    adds a routing hop (and a small markup) on top of the
    upstream vendor. Use <code>claude</code> for Anthropic,
    <code>gemini</code> for Google, and <code>fireworks</code>
    for open-weights models that Fireworks hosts directly.
    OpenRouter is the right call when the model you want is not
    on any of those.
  </p>
</div>

{#openai-compatible}
## Use any OpenAI-compatible endpoint

For any backend that speaks the OpenAI chat-completions wire format —
Together, Groq, DeepInfra, LiteLLM proxies, self-hosted vLLM — use
the `openai-compatible` provider. You must supply
the base URL and model ID explicitly:

<pre><code><span class="prompt">$</span> export OPENAI_COMPATIBLE_API_KEY="your-key-here"
<span class="prompt">$</span> cantrip --provider openai-compatible \
    --base-url https://api.together.xyz/v1 \
    --model meta-llama/Llama-3.3-70B-Instruct-Turbo</code></pre>

For endpoints that don't require authentication (e.g. a local
vLLM instance on your network), set
`OPENAI_COMPATIBLE_API_KEY` to any non-empty
string.

<div class="callout-warn callout">
  <p>
    Prefer a dedicated provider when one exists:
    <code>inference-snap</code> for Canonical's local servers,
    <code>fireworks</code> for Fireworks.ai. Dedicated providers
    carry sensible defaults and model-catalogue probing; the
    generic provider requires you to supply everything by hand.
  </p>
</div>

{#hybrid}
## Hybrid setups

You can combine providers — use a powerful cloud model for code
generation and a local model for internal tasks like research
summarisation and log queries:

<pre><code><span class="prompt">$</span> cantrip --provider claude \
    --light-provider inference-snap --light-snap nemotron-3-nano</code></pre>

`--light-provider` accepts `gemini`,
`claude`, `inference-snap`, `fireworks`, or
`openrouter`.
See [Configure light models](howto-light-models.html) for full
details on cost routing.
