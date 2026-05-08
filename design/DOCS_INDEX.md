# Indexed Charm-Ecosystem Documentation

Phase 72.1.  This document covers the docs-index subsystem — how it
crawls Canonical's documentation surfaces, embeds page content via
the Phase 72.3 role router, stores vectors in a per-site SQLite
cache, and surfaces hits through both an agent-invokable
`docs_search` tool and a user-facing `@docs <site> <query>` mention.

The implementation lives under `src/cantrip/docs_index/`:

- `store.py` — SQLite-backed vector store; pure-Python cosine
  similarity (no `sqlite-vec` / `faiss` dep).
- `chunk.py` — paragraph-aware chunker (~500 tokens, 50 overlap).
- `crawl.py` — sitemap.xml-driven crawler + HTML body extractor.
- `sites.py` — static registry of the six target sites.
- `index.py` — pipeline that ties crawl → chunk → embed → upsert.
- `cli.py` — `cantrip docs index|list|search` argparse handler.

The retrieval surfaces live alongside their consumers:

- `cantrip.agent.tools.docs_search.DocsSearchTool` — typed agent
  tool registered when the session has an embed-capable router.
- `cantrip.agent.context_providers_builtin.DocsProvider` — the
  Phase 72.2 `@docs <site> <query>` mention.

## Why we ship this

The single most common charm-authoring failure mode is an LLM
inventing a config option, hook name, or relation interface that
does not exist.  Anything the agent recalls from training is by
definition stale — Juju, ops, charmcraft, rockcraft, and jubilant
release on rolling cadences and release notes are *not* in the
training corpus the way Wikipedia is.  An indexed, cited-URL
retrieval surface fixes the hallucination at the source: the agent
can no longer fall back to plausible-sounding nonsense because the
canonical text is one tool call away.

## What it indexes

Six canonical Canonical surfaces (registered in `sites.py`):

| Site         | Sitemap                                                      |
|--------------|--------------------------------------------------------------|
| `juju`       | `documentation.ubuntu.com/juju/3.6/sitemap.xml`              |
| `ops`        | `documentation.ubuntu.com/ops/latest/sitemap.xml`            |
| `charmcraft` | `documentation.ubuntu.com/charmcraft/stable/sitemap.xml`     |
| `rockcraft`  | `documentation.ubuntu.com/rockcraft/stable/sitemap.xml`      |
| `jubilant`   | `documentation.ubuntu.com/jubilant/sitemap.xml`              |
| `charmlibs`  | `documentation.ubuntu.com/charmlibs/sitemap.xml`             |

The registry is *static* — only canonical sources, no arbitrary
URLs.  A user-extensible config can land later if a need emerges;
today's surface keeps the trust boundary clear.

## Pipeline

1.  **Sitemap fetch.**  Each site exposes `sitemap.xml`.  The
    crawler walks both flat (`<urlset>`) and index
    (`<sitemapindex>`) envelopes; nested sitemaps are followed up
    to depth 4.
2.  **Page fetch.**  Each URL whose host matches the site's home
    domain is downloaded.  Errors (timeouts, 404s, oversize) are
    absorbed and reported in `IndexReport.errors` so a single bad
    page does not abort the run.
3.  **HTML extraction.**  An `html.parser`-based flattener strips
    `<script>`, `<style>`, `<nav>`, `<footer>`, `<header>` and
    collapses whitespace, preserving paragraph and heading
    boundaries.
4.  **Chunk.**  Body text splits into ~500-token slices with
    50-token overlap.  Paragraph breaks beat sentence breaks beat
    whitespace breaks beat hard cuts so chunks rarely end mid-word.
5.  **Embed.**  Chunks batch in groups of 64 through the Phase 72.3
    `EmbedProvider`.  Embed cost rolls into `/cost` under the
    `embed` role.
6.  **Upsert.**  Per-site `DocsStore` writes the rows under
    `~/.cache/cantrip/docs-index/<site>/index.db`.  Each chunk has
    a stable `sha256(url|ordinal)` hash so re-indexing replaces
    rows rather than accumulating duplicates.

## Storage choice

Vectors are packed float32 BLOBs.  Similarity search runs as
pure-Python cosine over a single SELECT.  Charm-ecosystem doc
corpora are small — low thousands of chunks per site — so this
stays sub-second on a laptop without a native vector-store
dependency.  When a corpus outgrows in-memory search, swap in
`sqlite-vec` or `faiss` behind the same `DocsStore.upsert` /
`search` / `count` surface; nothing else in the package cares.

## Configuration

Configured via the same env-var / CLI-flag precedence as the rest
of Phase 72.3:

```bash
export CANTRIP_EMBED_PROVIDER=voyage
export VOYAGE_API_KEY=...

cantrip docs index --site ops          # index the ops reference
cantrip docs list                       # show registered + indexed sites
cantrip docs search ops "secrets"       # one-shot search from a shell
```

In a chat session:

```
@docs ops secrets         # mention; expands to top hits inline
docs_search(query="...")   # the agent's tool form (called automatically)
```

## Failure modes and their messages

| Failure                       | Surface                                              |
|-------------------------------|------------------------------------------------------|
| No embed provider configured  | `RoleNotConfigured` error pointing at env vars       |
| Site not indexed              | `cantrip docs index --site <name>` hint              |
| Page 404 / timeout            | Logged to `IndexReport.errors`; rest of crawl runs   |
| Empty query                   | Tool returns `success=False` with friendly message   |
| Unknown site name             | "Run `cantrip docs index`" hint, exit code 1         |
| Mid-corpus model rotation     | `DocsStore.models()` exposes the mix; users re-index |

## Out of scope here

* **Recursive BFS crawl.**  Every target site exposes a sitemap;
  unbounded link-graph following invites surface area we don't
  want.  If a future target has no sitemap, ship a per-site
  scraper next to the registry entry rather than turning on BFS
  globally.
* **Incremental refresh.**  V1 re-crawls everything on
  `cantrip docs index --site <name>`.  Per-page age tracking with
  `If-Modified-Since` honoring lands as 72.1b if a real corpus
  size makes the full re-crawl painful.
* **Sentence-transformers offline fallback.**  Phase 72.3
  deferred this; nothing in 72.1 changes that decision.  Sessions
  without a remote embed provider see `RoleNotConfigured` and
  cannot use the docs index — same behaviour as any other
  retrieval feature.
* **Native vector store.**  See "Storage choice" above —
  `sqlite-vec` or `faiss` swap in transparently when the simple
  cosine loop becomes the bottleneck.
