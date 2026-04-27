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

Cantrip's primary embed/rerank provider is Voyage (cloud, paid). For
users who want a local-first, free option, an inference snap is the
most aligned shape: it follows the same install/discovery pattern as
the chat snaps Cantrip already wires up (`gemma3`, `deepseek-r1`,
`qwen-vl`, `nemotron-3-nano`) and exposes an OpenAI-compatible
`/v1/embeddings` endpoint that the existing
[`OpenAIEmbedProvider`](../src/cantrip/llm/openai_embeddings.py) can
reach via `OPENAI_EMBED_BASE_URL` (no API key needed).

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

Once the snap is running locally, point Cantrip's
`OpenAIEmbedProvider` at it:

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
