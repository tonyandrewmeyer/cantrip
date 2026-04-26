"""Pipeline that ties crawl → chunk → embed → store (Phase 72.1).

Public entry point :func:`index_site` orchestrates the four stages
for one site:

1.  Fetch the sitemap to enumerate page URLs.
2.  For each page, fetch and extract HTML body + title.
3.  Chunk into ~500-token slices with 50-token overlap.
4.  Embed via the Phase 72.3 :class:`~cantrip.llm.roles.EmbedProvider`.
5.  Upsert into the per-site :class:`~cantrip.docs_index.store.DocsStore`.

The pipeline is *batch-aware*: chunks are accumulated and embedded
in batches of :data:`_EMBED_BATCH_SIZE` so a 2000-page site doesn't
trigger 2000 separate API calls.  Most embedding APIs accept up to
~96 inputs per call (Voyage's documented cap); 64 is the safe
default here.

The function does not catch :class:`~cantrip.llm.base.ProviderError`
— a misconfigured embed provider should fail loudly rather than
silently producing an empty corpus.  Per-page errors (timeouts,
404s) are absorbed inside :func:`~cantrip.docs_index.crawl.fetch_page`
so the rest of the crawl proceeds.
"""

from __future__ import annotations

import asyncio
import dataclasses
import logging
import pathlib
import urllib.parse
from collections.abc import Iterable

import httpx

from cantrip.docs_index import crawl, sites
from cantrip.docs_index.chunk import chunk_text
from cantrip.docs_index.store import Chunk, DocsStore
from cantrip.llm.roles import EmbedProvider, record_role_usage

log = logging.getLogger(__name__)


_EMBED_BATCH_SIZE = 64
_DEFAULT_CACHE_ROOT = pathlib.Path.home() / ".cache" / "cantrip" / "docs-index"


@dataclasses.dataclass(frozen=True, slots=True)
class IndexReport:
    """Summary of one indexing pass — surfaces in CLI + tests.

    ``pages_crawled`` counts pages successfully fetched and chunked.
    ``chunks_indexed`` counts rows actually upserted into the store
    (so a re-index of an unchanged site reports the full count even
    though the database content is identical).  ``embed_calls``
    counts the number of API batches executed; useful for
    rate-limit reasoning.  ``errors`` lists per-page failures for
    visibility without aborting the run.
    """

    site: str
    pages_crawled: int
    chunks_indexed: int
    embed_calls: int
    errors: tuple[str, ...] = ()


def cache_root() -> pathlib.Path:
    """Return the on-disk cache root for indexed sites."""
    return _DEFAULT_CACHE_ROOT


def store_path_for(site_name: str, *, root: pathlib.Path | None = None) -> pathlib.Path:
    """Return the SQLite path for *site_name* under *root* (default cache)."""
    base = root if root is not None else cache_root()
    return base / site_name / "index.db"


def _batched(items: list[str], size: int) -> Iterable[list[str]]:
    """Yield successive *size*-element slices of *items*."""
    for i in range(0, len(items), size):
        yield items[i : i + size]


async def index_site(
    site: sites.DocSite,
    embed_provider: EmbedProvider,
    *,
    root: pathlib.Path | None = None,
    store: DocsStore | None = None,
    client: httpx.AsyncClient | None = None,
    url_filter: list[str] | None = None,
    record_usage_to: object | None = None,
) -> IndexReport:
    """Crawl *site*, embed each chunk, and upsert into the per-site store.

    *root* overrides the on-disk cache directory (tests pass
    ``tmp_path``).  *store* lets a caller inject a pre-built
    :class:`DocsStore` — handy for tests with stubbed paths.
    *client* supplies an httpx.AsyncClient (tests pre-load mocked
    responses).  *url_filter*, when set, restricts the crawl to
    just the listed URLs — used by the CLI's ``--url`` selector
    and by tests that don't want a full sitemap walk.

    *record_usage_to* receives ``record_usage(...)`` calls for cost
    tracking; pass the agent's session store, or ``None`` to skip.
    """
    sweep = await _sweep_pages(site, client=client, url_filter=url_filter)

    target_store = store
    owns_store = target_store is None
    if target_store is None:
        target_store = DocsStore(site.name, store_path_for(site.name, root=root))

    errors: list[str] = []
    chunks_indexed = 0
    embed_calls = 0
    try:
        for page in sweep.pages:
            page_chunks = chunk_text(page.body)
            if not page_chunks:
                continue
            # Embed the page's chunks in one or more batches.
            page_records: list[Chunk] = []
            for batch_texts_idx in _batched([c.text for c in page_chunks], _EMBED_BATCH_SIZE):
                batch_result = await embed_provider.embed(batch_texts_idx)
                embed_calls += 1
                if record_usage_to is not None:
                    record_role_usage(
                        record_usage_to,
                        provider_id="(embed)",
                        model=batch_result.model,
                        input_tokens=batch_result.input_tokens,
                        role="embed",
                    )
                start = len(page_records)
                for offset, vec in enumerate(batch_result.vectors):
                    chunk = page_chunks[start + offset]
                    page_records.append(
                        Chunk(
                            url=page.url,
                            title=page.title,
                            section=_section_for(page.url),
                            ordinal=chunk.ordinal,
                            text=chunk.text,
                            vector=vec,
                            model=batch_result.model,
                        )
                    )
            # Replace the page's existing rows wholesale so an
            # earlier crawl with a different chunker doesn't leave
            # orphans.
            target_store.delete_url(page.url)
            chunks_indexed += target_store.upsert(page_records)
    finally:
        if owns_store:
            target_store.close()

    return IndexReport(
        site=site.name,
        pages_crawled=len(sweep.pages),
        chunks_indexed=chunks_indexed,
        embed_calls=embed_calls,
        errors=tuple(errors + list(sweep.errors)),
    )


@dataclasses.dataclass(frozen=True, slots=True)
class _SweepResult:
    """Internal — pages successfully fetched plus per-URL errors."""

    pages: tuple[crawl.CrawledPage, ...]
    errors: tuple[str, ...] = ()


async def _sweep_pages(
    site: sites.DocSite,
    *,
    client: httpx.AsyncClient | None,
    url_filter: list[str] | None,
) -> _SweepResult:
    """Fetch every page reachable from *site*'s sitemap.

    A *url_filter* short-circuits the sitemap walk: useful for the
    CLI's ``--url`` selector (re-crawl one page after a fix) and
    for tests that don't want a network sitemap fetch.
    """
    if url_filter is not None:
        urls = list(url_filter)
    else:
        urls = await crawl.fetch_sitemap_urls(site.sitemap_url, client=client)
    host = urllib.parse.urlparse(site.home_url).hostname or ""
    urls = crawl.filter_urls(urls, host=host) if host else urls
    pages: list[crawl.CrawledPage] = []
    errors: list[str] = []
    for url in urls:
        page = await crawl.fetch_page(url, client=client)
        if page is None:
            errors.append(url)
            continue
        pages.append(page)
    return _SweepResult(pages=tuple(pages), errors=tuple(errors))


def _section_for(url: str) -> str:
    """Best-effort section label from the URL path.

    Read-the-docs and juju.is URLs typically encode a section in
    their first path component (``/howto/...``, ``/explanation/...``).
    Returning that as the section gives users a navigation
    breadcrumb without needing per-site parsers.  Empty when the
    URL has no path.
    """
    parsed = urllib.parse.urlparse(url)
    parts = [p for p in parsed.path.split("/") if p]
    if not parts:
        return ""
    return parts[0]


async def _fanout(coros: list, concurrency: int) -> list:
    """Run *coros* with bounded concurrency; collect results in order.

    Used by tests and external callers that want a tighter
    concurrency cap than asyncio.gather's unbounded default.
    """
    sem = asyncio.Semaphore(concurrency)

    async def _run(coro):
        async with sem:
            return await coro

    return await asyncio.gather(*[_run(c) for c in coros])
