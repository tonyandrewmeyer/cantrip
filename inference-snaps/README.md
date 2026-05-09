# Inference snaps

This directory holds Cantrip-adjacent inference snaps — model servers
packaged as Ubuntu snaps following the [Canonical inference-snaps
framework](https://github.com/canonical/inference-snaps). They are
*not* part of the Cantrip Python package; they live in this repo
because the Cantrip provider layer consumes them and the two move
together.

Each subdirectory is a self-contained snapcraft project. Build,
install, and publish them independently.

## Why these exist

The snaps in this directory cover two shapes:

- **Embed snaps** (e.g. `embeddinggemma/`) — local-first, free
  alternative to Cantrip's primary embed/rerank provider (Voyage).
  Exposes an OpenAI-compatible `/v1/embeddings` endpoint that the
  existing
  [`OpenAIEmbedProvider`](../src/cantrip/llm/openai_embeddings.py)
  reaches via `OPENAI_EMBED_BASE_URL` (no API key needed).
- **Chat snaps for charm-coding** (e.g. `qwen3-coder/`) — a code-tuned
  alternative to the Canonical-published chat snaps Cantrip already
  wires up (`gemma3`, `deepseek-r1`, `qwen-vl`, `nemotron-3-nano`),
  none of which are specialised for code. Exposes an
  OpenAI-compatible `/v1/chat/completions` endpoint that the existing
  [`InferenceSnapProvider`](../src/cantrip/llm/inference_snap.py)
  drives.

## Namespacing

Canonical owns the unsuffixed names in the snap store (`gemma3`,
`embeddinggemma`, etc.). These snaps are published under personal or
organisation namespaces — append a `-<namespace>` suffix to the snap
name in `snapcraft.yaml`. The *directory* name here stays clean
(e.g. `embeddinggemma/`) so a future Canonical-published snap can
take over without a rename.

## Available snaps

| Directory | Model | Role | Status |
|---|---|---|---|
| [`embeddinggemma/`](embeddinggemma/) | EmbeddingGemma 300M | embed | Scaffold, not built |
| [`qwen3-coder/`](qwen3-coder/) | Qwen3-Coder 30B-A3B Instruct (Q4_K_M) | chat (code) | Scaffold, not built |
| [`qwen3-8b/`](qwen3-8b/) | Qwen3-8B Instruct (Q4_K_M) | chat (general, GPU-fit) | Phase 105.1 smoke scaffold (no `snapcraft.yaml` yet) |
| [`qwen3-14b/`](qwen3-14b/) | Qwen3-14B (Q4_K_M) | chat (general, GPU-fit at 16 K) | Phase 105.1.5 smoke scaffold (no `snapcraft.yaml` yet) |
| [`deepseek-coder-v2-lite/`](deepseek-coder-v2-lite/) | DeepSeek-Coder-V2-Lite-Instruct (16 B MoE Q4_K_M) | chat (code-tuned, MoE, MLA) | Phase 105.1.6 smoke scaffold (no `snapcraft.yaml` yet) |
| [`mistral-nemo-12b/`](mistral-nemo-12b/) | Mistral Nemo 12B Instruct (Q4_K_M) | chat (general, native function calling, 128 K context) | Phase 105.1.7 smoke scaffold (no `snapcraft.yaml` yet) |

## Building a snap

```bash
cd inference-snaps/<snap-name>
./prepare-models.sh        # downloads GGUF weights from Hugging Face
snapcraft pack             # produces .snap + .comp files
sudo snap install --dangerous *.snap
sudo snap install --dangerous *.comp
sudo snap connect <snap-name>:hardware-observe
sudo <snap-name> use-engine --auto
sudo snap start <snap-name>
```

## Wiring into Cantrip

### Embed snaps

Point Cantrip's `OpenAIEmbedProvider` at the running snap:

```bash
# Discover the endpoint (varies per snap)
<snap-name> status

# Then:
export OPENAI_EMBED_BASE_URL="http://localhost:<port>/v1"
cantrip --provider claude \
    --embed-provider openai --embed-model <model-name>
```

The keyless override path was added in
[`feat(embed): allow keyless OpenAIEmbedProvider with custom base URL`](../CHANGELOG.md);
no `OPENAI_API_KEY` is needed.

### Chat snaps

Drive a chat snap directly through `InferenceSnapProvider`:

```bash
cantrip run --provider inference-snap \
    --snap <snap-name> --base-url http://localhost:<port>/v1
```

Once a chat snap stabilises, add it to `_SNAP_DEFAULTS` in
[`src/cantrip/llm/inference_snap.py`](../src/cantrip/llm/inference_snap.py)
so `--snap <name>` discovers it automatically.
