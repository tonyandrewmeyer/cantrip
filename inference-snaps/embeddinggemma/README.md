# embeddinggemma snap

An Ubuntu snap that runs Google's
[EmbeddingGemma-300M](https://ai.google.dev/gemma/docs/embeddinggemma)
text-embedding model via `llama.cpp`'s OpenAI-compatible HTTP server.

This is a *scaffold* — the structural pieces are in place but the
GGUF model file, the snap-name namespace, and the snap-store upload
flow are intentionally left to the human builder.

## What it ships

- **One model:** EmbeddingGemma 300M, Q8_0 quantisation (~330 MB,
  near-fp16 quality).
- **One engine:** `cpu` — runs on any amd64 or arm64 CPU. EmbeddingGemma
  is small enough that GPU acceleration is rarely worth the extra
  packaging complexity for a v0.
- **One runtime:** `llama.cpp` from
  [`canonical/llama.cpp-builds`](https://github.com/canonical/llama.cpp-builds),
  invoked with `--embedding --pooling mean` to put the server in
  embedding mode.
- **OpenAI-compatible endpoint** at `http://localhost:<port>/v1`.
  `POST /v1/embeddings` returns the standard `{data: [{embedding:
  [...], index: 0}], usage: {prompt_tokens: N}}` shape that
  Cantrip's `OpenAIEmbedProvider` already parses.

## Before you build

1. **Pick a snap-store namespace.** Edit `snap/snapcraft.yaml` and
   replace `embeddinggemma-CHANGEME` with your namespaced name (e.g.
   `embeddinggemma-tonymeyer`). Register it on the snap store before
   the first upload — see
   <https://snapcraft.io/docs/reference/development/registering-your-app-name/>.

2. **Accept the Gemma terms** on Hugging Face. EmbeddingGemma is
   gated; you must accept the licence at
   <https://huggingface.co/google/embeddinggemma-300m> while logged
   in.

3. **Drop the licence file** at `LICENSE-gemma.md`. Download it from
   <https://ai.google.dev/gemma/terms> and commit it (the Gemma
   terms permit redistribution alongside the model).

4. **Choose your GGUF source.** Google does not yet ship official
   GGUFs for EmbeddingGemma; community conversions are on
   Hugging Face under e.g.
   `mradermacher/EmbeddingGemma-300m-GGUF`. Edit
   `prepare-models.sh` with the URL and filename you trust.

## Build and test locally

```bash
# 1. Download the model GGUF
./prepare-models.sh

# 2. Pack the snap
snapcraft pack

# 3. Install the snap and its components
sudo snap install --dangerous embeddinggemma-*_*.snap
sudo snap install --dangerous embeddinggemma-*+*.comp

# 4. Grant hardware-observe (needed for engine selection)
sudo snap connect embeddinggemma-CHANGEME:hardware-observe

# 5. Pick an engine and start the server
sudo embeddinggemma-CHANGEME use-engine --auto
sudo snap start embeddinggemma-CHANGEME

# 6. Smoke-test
curl http://localhost:8331/v1/embeddings \
  -H 'Content-Type: application/json' \
  -d '{"model":"embeddinggemma","input":"Juju is an application modelling tool"}'
```

The default port (8331) is set in `snap/hooks/install`; change it if
it collides with the Canonical inference snaps already in your
`_SNAP_DEFAULTS` table (gemma3=8328, deepseek-r1=8324, qwen-vl=8326,
nemotron-3-nano=8330).

## Wire into Cantrip

```bash
export OPENAI_EMBED_BASE_URL="http://localhost:8331/v1"
cantrip --provider claude \
    --embed-provider openai --embed-model embeddinggemma
```

Once you're happy with the local snap, follow up with a small patch
to `src/cantrip/llm/inference_snap.py` adding the snap to
`_SNAP_DEFAULTS` and exposing it via
`--embed-provider inference-snap`. That short-circuits the
`OPENAI_EMBED_BASE_URL` shuffle.

## Publishing

```bash
# First-time only: register the name and request component upload permission.
# https://snapcraft.io/docs/reference/development/registering-your-app-name/
# https://forum.snapcraft.io/c/store-requests/19

snapcraft upload embeddinggemma-*.snap \
  --component model-300m-q8-0-gguf=embeddinggemma-*+model-300m-q8-0-gguf.comp \
  --component llamacpp=embeddinggemma-*+llamacpp.comp \
  --release edge
```

## Licensing

- **Snap packaging code** in this directory: same licence as the
  rest of Cantrip (see top-level `LICENSE`).
- **Model weights**: Gemma Terms of Use
  (<https://ai.google.dev/gemma/terms>). Redistribution is permitted
  alongside the model; commercial use is allowed under the standard
  Gemma conditions.
- **`llama.cpp`**: MIT.

## Known gaps in this scaffold

- No GPU engines (CUDA, ROCm, Intel). EmbeddingGemma is fast enough
  on CPU that v0 doesn't need them; add them later if a user reports
  CPU latency that hurts.
- No `chat` subcommand wired into the CLI app — embedding-only snaps
  don't have a meaningful chat surface. The `modelctl status` and
  `use-engine` commands still work as expected.
- No tab-completion script; copy `scripts/completion.bash` from the
  gemma3 snap when you wire that up.
- No CI. Snapcraft builds inside LXD/multipass and would need a
  separate runner; defer until the snap stabilises.
