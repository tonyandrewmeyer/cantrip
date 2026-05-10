---
title: "How to choose an LLM provider — Cantrip"
description: "Select the right LLM provider for Cantrip: inference snaps, Gemini, Claude, Fireworks.ai, OpenRouter, OpenCode Zen, or any OpenAI-compatible endpoint."
h1: "Choose an LLM provider"
subtitle: "Cantrip supports seven LLM providers. This guide helps you pick the right one for your situation."
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
| **OpenCode Zen** | Yes (`OPENCODE_ZEN_API_KEY`) | OpenCode's curated gateway to Claude, GPT-5, Gemini 3, GLM, Kimi, Qwen behind one key | Paid (free tier) |
| **OpenAI-compatible** | Yes (`OPENAI_COMPATIBLE_API_KEY`) | Any other OpenAI-compatible endpoint (Together, Groq, vLLM, …) | Depends |

{#env-vars}
## Set up environment variables

Each cloud provider needs its API key in an environment variable. The
sections below show the one-line `export` for each provider; pick one
and you are set.

For a key to survive new shells, add the export to your shell profile
(`~/.bashrc`, `~/.zshrc`, `~/.config/fish/config.fish`):

<pre><code><span class="prompt">$</span> echo 'export GEMINI_API_KEY="your-key-here"' &gt;&gt; ~/.bashrc
<span class="prompt">$</span> source ~/.bashrc</code></pre>

A one-shot `export` in the current shell is enough for testing — it
just disappears when the terminal closes.

This page is the setup walk-through for **provider keys** and the
**embed / rerank role** keys. Operational tunables — memory directory
overrides, MCP token storage, snapshot toggles, the self-update
opt-out, and the rest — live in the
[CLI reference](reference-cli.html#env-vars). Reach for that page when
you want a single table of every variable Cantrip reads.

{#inference-snap}
## Use local inference snaps

Ubuntu inference snaps are the Canonical-native path: a production-grade
OpenAI-compatible server, installed from the Snap Store, running models
locally on your GPU with no API key or internet connection required.
Install the snap first:

<pre><code><span class="prompt">$</span> sudo snap install gemma3
<span class="prompt">$</span> cantrip --provider inference-snap --snap gemma3</code></pre>

Other supported snaps include `gemma4` (Gemma 3n E4B, multimodal),
`nemotron-3-nano` for lighter workloads, `qwen3-coder` for
code-focused work with native tool calling, and `qwen-vl` for
vision tasks. The quality of output depends on your GPU and the
model size.

<div class="callout-warn callout">
  <p>
    Local models produce lower-quality output than cloud APIs,
    particularly for complex charm paths. Consider using a cloud
    provider for the primary model and a local model for
    <a href="howto-light-models.html">light tasks</a>.
  </p>
</div>

Cantrip clamps the conversation temperature to 0.2 for the
inference-snap provider — the local quantised models intermittently
break out of the OpenAI tool-call envelope at the frontier-default
0.7 and emit raw chat-template scaffolding inside the assistant
content, which the conversation loop then mistakes for a final
reply. The clamp is per-provider; cloud APIs still run at 0.7.

The provider also auto-detects the runtime per-slot context size
from llama.cpp's <code>/slots</code> and <code>/props</code>
endpoints. The trained context (often 128 K or 256 K) is usually
bigger than the per-slot budget the snap actually serves
(typically 8 K – 32 K depending on <code>--ctx-size</code> and
<code>--parallel</code>); without the runtime probe Cantrip would
treat the model as having far more headroom than it does and skip
compaction entirely. Run <code>&lt;snap-name&gt; status</code> if
you suspect the wrong context size — Cantrip logs the
runtime/trained mismatch at INFO when it downgrades.

### Tune the snap HTTP read timeout

Slow local snaps (qwen3-coder on a partial-offload setup, large
quantised models on smaller GPUs) can take 8–15 minutes to finish a
single big-file rewrite once the conversation is several KB long.
Cantrip ships a 1200 s (20 min) read timeout by default — long
enough for any plausible single-turn generation on the slowest
local snap, short enough that a genuinely stuck server doesn't hang
the conversation forever.

Override the timeout on faster GPUs to fail-fast instead:

<pre><code><span class="prompt">$</span> cantrip --provider inference-snap --snap qwen3-coder --snap-read-timeout 300
<span class="prompt">$</span> CANTRIP_SNAP_READ_TIMEOUT=600 cantrip --provider inference-snap --snap gemma4</code></pre>

The CLI flag wins over the environment variable, which wins over the
1200 s default. A non-numeric or non-positive value logs a warning and
falls back to the default rather than crashing.

When the snap drops mid-stream (the qwen3-coder snap occasionally hangs
up at long generations), Cantrip surfaces the recovery as a
<code>[provider reconnect]</code> system message in the chat and
retries with a short exponential backoff (~2/4/8 s) before giving up.
The conversation loop stays alive across the retry — no need to
re-launch.

### Short-session mode for tight-context snaps

Some snaps run with a small per-slot context window — gemma4 (Gemma 3n
E4B) gives roughly 10&nbsp;K tokens per slot, and the system prompt plus
tool schemas already fill a third of that before a conversation starts.
Cantrip detects this at startup: when the usable window is below
~16&nbsp;K it switches into **short-session mode**, which compacts at
50&nbsp;% of the window instead of 80&nbsp;%, replaces the prose-summary
compaction with a one-line-per-tool-call *history ledger* (dropping the
raw older messages rather than keeping them around), trims the toolset to
just what the current phase needs, and treats each turn as a near-fresh
conversation. The status bar shows a <code>[short-session]</code> chip
while it is active, and <code>/cost</code> reports the compaction
strategy. The trade-off is real — the agent loses some cross-edit memory,
so a debugging loop that spans several files will be weaker than it would
be on a roomier model — but it lets a 10&nbsp;K model actually finish a
multi-edit charm without erroring on <code>exceed_context_size</code>.

Force the mode with `--short-session=on|off` (or `CANTRIP_SHORT_SESSION`)
to opt a borderline ~16–32&nbsp;K provider in or out:

<pre><code><span class="prompt">$</span> cantrip --provider inference-snap --snap qwen3-coder --short-session on</code></pre>

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

{#opencode-zen}
## Use OpenCode Zen

OpenCode Zen is a curated model gateway run by the
[OpenCode](https://opencode.ai) project. It exposes Anthropic Claude
(Opus, Sonnet, Haiku), OpenAI GPT-5 family, Gemini 3 family, and a
handful of strong open-weights models (GLM, Kimi, Qwen, MiniMax)
behind a single OpenAI-compatible API and a single key, with a free
tier for the lighter models.

Get a key from the [OpenCode Zen page](https://opencode.ai/zen),
then:

<pre><code><span class="prompt">$</span> export OPENCODE_ZEN_API_KEY="your-key-here"
<span class="prompt">$</span> cantrip --provider opencode-zen</code></pre>

The default model is `claude-haiku-4-5` — fast, cheap, with native
tool use. Override with any Zen slug (no vendor prefix):

<pre><code><span class="prompt">$</span> cantrip --provider opencode-zen --model gpt-5.5

<span class="prompt">$</span> cantrip --provider opencode-zen --model gemini-3.1-pro

<span class="prompt">$</span> cantrip --provider opencode-zen --model kimi-k2.6</code></pre>

The legacy `ZEN_API_KEY` environment variable is also accepted as a
fallback when `OPENCODE_ZEN_API_KEY` is unset.

<div class="callout-note callout">
  <p>
    Like OpenRouter, Zen adds a routing hop on top of the upstream
    vendor. Prefer a dedicated provider when one exists —
    <code>claude</code> for Anthropic, <code>gemini</code> for
    Google, <code>fireworks</code> for the open-weights models
    Fireworks hosts directly. Reach for <code>opencode-zen</code>
    when you want OpenCode's curation, its free tier, or a model
    only available there.
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

{#retrieval-roles}
## Configure embed and rerank

Retrieval features &mdash; the planned `@docs` index and memory recall
&mdash; need an *embedding* provider, and rerank quality benefits
from a dedicated rerank provider.  Cantrip routes these via a
separate `RoleRouter` so you pick them independently of the chat
provider.

The Anthropic-ecosystem recommendation is Voyage:

<pre><code><span class="prompt">$</span> export VOYAGE_API_KEY=...
<span class="prompt">$</span> cantrip --provider claude \
    --embed-provider voyage --embed-model voyage-3 \
    --rerank-provider voyage --rerank-model rerank-2</code></pre>

OpenAI users can pair their embed endpoint with Voyage rerank
(OpenAI does not ship a rerank API):

<pre><code><span class="prompt">$</span> export OPENAI_API_KEY=... VOYAGE_API_KEY=...
<span class="prompt">$</span> cantrip --provider claude \
    --embed-provider openai --embed-model text-embedding-3-large \
    --rerank-provider voyage</code></pre>

Equivalent environment variables for stable shells:
`CANTRIP_EMBED_PROVIDER`, `CANTRIP_EMBED_MODEL`,
`CANTRIP_RERANK_PROVIDER`, `CANTRIP_RERANK_MODEL`.  The CLI flag
wins when both are present.

### Local embed servers (Ollama, vLLM, llama.cpp)

Anything that exposes the OpenAI `/v1/embeddings` wire format can
serve as the embed provider.  Set `OPENAI_EMBED_BASE_URL` to the
endpoint &mdash; the API-key requirement is automatically relaxed
when this override is present, since most local servers do not
authenticate.

<pre><code><span class="prompt">$</span> ollama pull nomic-embed-text
<span class="prompt">$</span> export OPENAI_EMBED_BASE_URL="http://localhost:11434/v1"
<span class="prompt">$</span> cantrip --provider claude \
    --embed-provider openai --embed-model nomic-embed-text \
    --rerank-provider voyage</code></pre>

Tested shapes:

- **Ollama** &mdash; `http://localhost:11434/v1`, model name matches
  the pulled tag (e.g. `nomic-embed-text`, `mxbai-embed-large`,
  `bge-m3`).
- **vLLM** &mdash; `http://localhost:8000/v1` when launched with
  `vllm serve <embed-model> --task embed`.
- **llama.cpp `llama-server`** &mdash; `http://localhost:8080/v1`
  when launched with `--embedding --pooling mean`.
- **Canonical inference snaps** &mdash; the chat snaps (gemma3,
  gemma4, deepseek-r1, etc.) do not expose `/v1/embeddings`; an
  embed-only inference snap is in development.

If the local server *does* require authentication, set
`OPENAI_API_KEY` alongside `OPENAI_EMBED_BASE_URL` and the bearer
token will be forwarded.

Costs surface in `/cost` under a separate **By role** section once
an embed or rerank call has fired, so retrieval spend is visible
without merging into chat.  Pricing entries cover voyage-3,
voyage-3-lite, voyage-3-large, voyage-code-3, rerank-2,
rerank-2-lite, text-embedding-3-small, and text-embedding-3-large;
unknown models render as `free`.

An offline sentence-transformers fallback is on the roadmap but not
yet shipped &mdash; sessions without a configured embed provider
raise `RoleNotConfigured` from the first retrieval call rather than
silently degrading.

{#hybrid}
## Hybrid setups

You can combine providers — use a powerful cloud model for code
generation and a local model for internal tasks like research
summarisation and log queries:

<pre><code><span class="prompt">$</span> cantrip --provider claude \
    --light-provider inference-snap --light-snap nemotron-3-nano</code></pre>

`--light-provider` accepts `gemini`,
`claude`, `inference-snap`, `fireworks`,
`openrouter`, or `opencode-zen`.
See [Configure light models](howto-light-models.html) for full
details on cost routing.
