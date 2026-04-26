# Provider Roles — Embed and Rerank

Phase 72.3.  This document covers the retrieval-side provider roles
Cantrip exposes alongside the existing chat / edit / apply path.
The implementation lives in `src/cantrip/llm/roles.py` (ABCs and
:class:`RoleRouter`), `src/cantrip/llm/voyage.py` (Anthropic-ecosystem
recommendation), and `src/cantrip/llm/openai_embeddings.py`.

## Why a separate ABC

`LLMProvider` (`src/cantrip/llm/base.py`) is built around
conversational completion — messages in, tool calls and streamed
tokens out, with a system-prompt slot, a thinking-budget knob, and
a streaming envelope.  Embedding and reranking are *not*
conversational: they take a flat list of inputs, return a flat
result, and have no notion of system prompt, tool calls, or
extended thinking.

Wedging them into `LLMProvider` would force every chat provider
(Claude, Gemini, OpenAI-compat) to grow no-op overrides for endpoints
they cannot speak.  Two narrower ABCs sidestep that:

* `EmbedProvider` — `embed(texts) -> EmbeddingResult`
* `RerankProvider` — `rerank(query, documents) -> RerankResult`

A provider may implement one, the other, both, or neither.

## The router

`RoleRouter` ties roles to provider instances:

```python
router = RoleRouter()
router.register_embed(VoyageEmbedProvider(model="voyage-3"))
router.register_rerank(VoyageRerankProvider(model="rerank-2"))
```

Retrieval-using callers — Phase 72.1 `@docs`, Phase 43 memory
retrieval — query the router rather than instantiating providers
directly:

```python
embed_provider = agent.role_router.get_embed()
result = await embed_provider.embed(texts)
```

When the role is unconfigured `RoleNotConfigured` raises with a
message naming the env var / CLI flag that would configure it.

## Configuration

Env vars (lowest precedence) and CLI flags (overrides):

| Setting          | Env var                     | CLI flag             |
|------------------|-----------------------------|----------------------|
| Embed provider   | `CANTRIP_EMBED_PROVIDER`    | `--embed-provider`   |
| Embed model      | `CANTRIP_EMBED_MODEL`       | `--embed-model`      |
| Rerank provider  | `CANTRIP_RERANK_PROVIDER`   | `--rerank-provider`  |
| Rerank model     | `CANTRIP_RERANK_MODEL`      | `--rerank-model`     |

Provider IDs:

* `voyage` — `VoyageEmbedProvider`, `VoyageRerankProvider`
* `openai` — `OpenAIEmbedProvider` (no rerank)

API keys: `VOYAGE_API_KEY` for Voyage; `OPENAI_API_KEY` for OpenAI.
Missing-key errors fire at agent boot (in `build_role_router`)
rather than at the first retrieval call.

`build_role_router(...)` is the single entry point each surface
calls — see `cli.py`, `tui/app.py`, `web/server.py`,
`print_mode.py` — so the precedence and error path stay in one
place.

## Cost accounting

The session store's `token_usage` table grew a `role` column
(schema version 13).  Each embed/rerank call records:

```python
record_role_usage(
    store,
    provider_id="voyage",
    model="voyage-3",
    input_tokens=result.input_tokens,
    role="embed",
)
```

`/cost` picks up a `**By role**` section once any non-chat row
exists, so retrieval spend separates from chat spend without
losing the per-model breakdown.  Legacy rows (NULL role) roll into
the `chat` bucket so historical totals stay honest.

Pricing entries (`cantrip.llm.pricing`) cover voyage-3 / -lite /
-large / -code-3, rerank-2 / -lite, and text-embedding-3-small /
-large.  Embed/rerank are input-only so `completion` is zero in
each entry.

## Adding a provider

1.  Implement the relevant ABC.  An async `embed`/`rerank` method
    plus a `model_name` property is the whole surface.
2.  Add a branch to `_make_embed_provider` /
    `_make_rerank_provider` in `cantrip.llm.roles` so the new
    provider shows up under its ID.
3.  Add pricing entries to `cantrip.llm.pricing` (input-only —
    `completion=0.0`).
4.  Tests: build a `RoleRouter`, register the provider, and call
    through the router.  Mock `httpx.AsyncClient.post` for wire
    coverage; do not hit the real API.

## Out of scope here

* **Sentence-transformers offline fallback.**  The roadmap calls
  for it; deferred until a concrete caller hits the embed path
  (currently 72.1 `@docs` is the only future caller, and it
  defaults to a remote provider).  When added, ship as an
  optional dependency (`uv add sentence-transformers`) and
  register a third provider ID, e.g. `local`.
* **Configuration via `cantrip.yaml`.**  Cantrip uses env vars and
  CLI flags everywhere; introducing a YAML config file alongside
  the existing surface would be a separate phase.  When that
  arrives, `build_role_router` keeps its current signature and
  the YAML loader fills the kwargs.
* **`summarize` and other chat-shaped roles.**  Those flow
  through the existing primary + light providers.  The router
  only owns the roles that can't be served by a chat provider.
