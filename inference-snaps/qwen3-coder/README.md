# qwen3-coder snap

An Ubuntu snap that runs Alibaba's
[Qwen3-Coder-30B-A3B-Instruct](https://huggingface.co/Qwen/Qwen3-Coder-30B-A3B-Instruct)
code model via `llama.cpp`'s OpenAI-compatible HTTP server.

This is a *scaffold* — the structural pieces are in place but the
GGUF model file, the snap-name namespace, and the snap-store upload
flow are intentionally left to the human builder.

## Why this model

The Canonical-published chat snaps Cantrip already wires up
(`gemma3`, `deepseek-r1`, `qwen-vl`, `nemotron-3-nano`) are general /
reasoning / vision models — none are specialised for code. Charm
work is Python on the `ops` framework; a code-tuned model trained
heavily on GitHub Python noticeably outperforms a general-purpose
model of the same size for that task.

Qwen3-Coder-30B-A3B-Instruct is the right shape for CPU-only
inference because it's a **Mixture-of-Experts** model with ~3B
active parameters per token. Generation throughput is roughly that
of a 3B dense model (on a modern 16-core CPU, expect ~35–50 tok/s),
while quality tracks much larger dense models on coding benchmarks.
It also has native tool-calling baked into its chat template, which
is what Cantrip drives over the OpenAI-compatible endpoint.

## What it ships

- **One model:** Qwen3-Coder-30B-A3B-Instruct, Q4_K_M quantisation
  (~17GB on disk). Q4_K_M is the sweet spot for code generation on
  CPU; Q5_K_M (~21GB) buys marginal quality at meaningful speed and
  RAM cost.
- **One engine:** `cpu` — runs on any modern amd64 or arm64 CPU.
  GPU engines aren't bundled because the target user runs this in a
  Multipass VM without GPU passthrough.
- **One runtime:** `llama.cpp` from
  [`canonical/llama.cpp-builds`](https://github.com/canonical/llama.cpp-builds),
  invoked with `--jinja` so the GGUF's embedded Jinja2 chat template
  is used (required for Qwen3-Coder's native tool-call rendering).
- **OpenAI-compatible endpoint** at `http://localhost:<port>/v1`.
  `POST /v1/chat/completions` with the standard tool-calling shape
  matches what Cantrip's `InferenceSnapProvider` already expects.

## Sizing

- **Disk:** ~20GB for the model component, plus a few GB for snap
  build artefacts and llama.cpp. Plan for ~25GB free during the
  first build.
- **RAM:** weights are ~17GB resident; the KV cache for the default
  32k context adds 4–8GB. Budget ~24GB free for comfortable
  operation; the engine declares `memory: 24G` to make the
  requirement explicit.

## Before you build

1. **Snap-store namespace.** The snap is named
   `qwen3-coder-tonyandrewmeyer`. Local builds
   (`snapcraft pack` + `snap install --dangerous`) work without
   registration. Register the name only before the first upload —
   see
   <https://snapcraft.io/docs/reference/development/registering-your-app-name/>.

2. **Verify the model licence.** Qwen3-Coder-30B-A3B-Instruct is
   published under Apache 2.0 at the time of writing (no gating, no
   acceptance step required). Confirm the licence on the
   [model card](https://huggingface.co/Qwen/Qwen3-Coder-30B-A3B-Instruct)
   before publishing a snap built from these weights.

3. **Choose your GGUF source.** Qwen does not ship official GGUFs
   for every release; community conversions live on Hugging Face
   under repos like `bartowski/...` (a widely-trusted GGUF
   maintainer). Edit `prepare-models.sh` if you'd rather pin a
   different conversion.

## Build and test locally

```bash
# 1. Download the model GGUF (~17GB).
./prepare-models.sh

# 2. Pack the snap.
snapcraft pack

# 3. Install the snap and its components.
sudo snap install --dangerous qwen3-coder-*_*.snap
sudo snap install --dangerous qwen3-coder-*+*.comp

# 4. Grant hardware-observe (needed for engine selection).
sudo snap connect qwen3-coder-tonyandrewmeyer:hardware-observe

# 5. Pick an engine and start the server.
sudo qwen3-coder-tonyandrewmeyer use-engine --auto
sudo snap start qwen3-coder-tonyandrewmeyer

# 6. Smoke-test (chat completion).
curl http://localhost:8332/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{
    "model": "qwen3-coder",
    "messages": [
      {"role": "user", "content": "Write a Juju charm in Python that pebble-execs a hello-world web server."}
    ],
    "max_tokens": 512
  }'
```

The default port (8332) is set in `snap/hooks/install`; change it if
it collides with the snaps already in your `_SNAP_DEFAULTS` table
(gemma3=8328, deepseek-r1=8324, qwen-vl=8326, nemotron-3-nano=8330,
embeddinggemma=8331).

## Wire into Cantrip

Once the snap is running locally, Cantrip's
`InferenceSnapProvider` can talk to it via the OpenAI-compatible
endpoint. Until the snap is added to `_SNAP_DEFAULTS`, point at it
explicitly with `--snap` (used for `<snap> status` discovery) and
`--base-url` (which overrides the discovered URL):

```bash
cantrip run --provider inference-snap \
    --snap qwen3-coder-tonyandrewmeyer \
    --base-url http://localhost:8332/v1
```

When you're happy with the local snap, follow up with a small patch
to `src/cantrip/llm/inference_snap.py`:

- Add `"qwen3-coder": 8332` to `_SNAP_DEFAULTS`.
- Update `discover_snap_endpoint` if your installed snap name is
  suffixed (`qwen3-coder-tonyandrewmeyer`) and the discovery code
  needs to know about both.

That short-circuits the explicit `--base-url` shuffle.

## Speculative decoding (follow-up)

llama.cpp's `--draft-model` flag pairs a small fast model as a
speculator against the large target model and can yield 1.3–1.7×
end-to-end throughput at no quality cost. For Qwen3-Coder-30B-A3B
the natural draft is a small Qwen3 (e.g. Qwen3-Coder 0.5B / 1.5B if
released, or a small instruct Qwen3 of similar tokeniser). Worth
trying after the base snap works; defer until throughput is
measured.

## Publishing

```bash
# First-time only: register the name and request component upload permission.
# https://snapcraft.io/docs/reference/development/registering-your-app-name/
# https://forum.snapcraft.io/c/store-requests/19

snapcraft upload qwen3-coder-*.snap \
  --component model-30b-a3b-q4-k-m-gguf=qwen3-coder-*+model-30b-a3b-q4-k-m-gguf.comp \
  --component llamacpp=qwen3-coder-*+llamacpp.comp \
  --release edge
```

## Licensing

- **Snap packaging code** in this directory: same licence as the
  rest of Cantrip (see top-level `LICENSE`).
- **Model weights**: Apache License 2.0 per the upstream model card
  at the time of writing — verify before redistribution.
- **`llama.cpp`**: MIT.

## Known gaps in this scaffold

- No GPU engines (CUDA, ROCm, Intel). Add them later if a user with
  a GPU needs more throughput than CPU-only delivers.
- No tab-completion script; copy `scripts/completion.bash` from a
  Canonical chat snap when wiring that up.
- No CI. Snapcraft builds inside LXD/multipass and would need a
  separate runner; defer until the snap stabilises.
- No automatic registration in `_SNAP_DEFAULTS` — see "Wire into
  Cantrip" above for the follow-up patch.
