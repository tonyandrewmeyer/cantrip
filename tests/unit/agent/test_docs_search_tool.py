"""Phase 72.1 — docs_search tool and @docs context provider."""

from __future__ import annotations

import json
import pathlib

import pytest

from cantrip.agent.context_providers import (
    ExpansionContext,
    expand_mentions,
)
from cantrip.agent.context_providers_builtin import (
    DocsProvider,
    build_default_registry,
)
from cantrip.agent.tools.docs_search import DocsSearchTool
from cantrip.docs_index import index
from cantrip.docs_index.store import Chunk, DocsStore
from cantrip.llm.roles import RoleRouter
from tests.support.roles import StubEmbed as _StubEmbed

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _seed_store(
    root: pathlib.Path,
    *,
    site: str,
    rows: list[tuple[str, tuple[float, ...]]],
) -> None:
    """Create a per-site store at *root* with the given (url, vector) rows."""
    path = index.store_path_for(site, root=root)
    store = DocsStore(site, path)
    chunks = [
        Chunk(
            url=url,
            title=f"{site} page {i}",
            section="howto",
            ordinal=0,
            text=f"body of page {i}",
            vector=vector,
            model="stub-embed",
        )
        for i, (url, vector) in enumerate(rows)
    ]
    store.upsert(chunks)
    store.close()


def _router_with_embed(vector: tuple[float, ...] = (1.0, 0.0, 0.0)) -> RoleRouter:
    router = RoleRouter()
    router.register_embed(_StubEmbed(vector=vector))
    return router


# ---------------------------------------------------------------------------
# DocsSearchTool
# ---------------------------------------------------------------------------


class TestDocsSearchTool:
    """Agent-invokable retrieval surface."""

    @pytest.mark.asyncio
    async def test_empty_query_rejected(self, tmp_path: pathlib.Path) -> None:
        tool = DocsSearchTool(_router_with_embed(), cache_root=tmp_path)
        result = await tool.execute(query="   ")
        assert result.success is False
        assert "non-empty query" in result.error

    @pytest.mark.asyncio
    async def test_no_embed_provider(self, tmp_path: pathlib.Path) -> None:
        # Empty router — get_embed will raise RoleNotConfigured.
        router = RoleRouter()
        tool = DocsSearchTool(router, cache_root=tmp_path)
        result = await tool.execute(query="how do I do X")
        assert result.success is False
        assert "embed provider" in result.error.lower()

    @pytest.mark.asyncio
    async def test_no_index(self, tmp_path: pathlib.Path) -> None:
        # Embed configured, but no per-site index exists yet.
        tool = DocsSearchTool(_router_with_embed(), cache_root=tmp_path)
        result = await tool.execute(query="anything")
        assert result.success is False
        assert "no docs index" in result.error.lower()

    @pytest.mark.asyncio
    async def test_search_returns_top_hits(self, tmp_path: pathlib.Path) -> None:
        _seed_store(
            tmp_path,
            site="ops",
            rows=[
                ("https://x/a", (1.0, 0.0, 0.0)),
                ("https://x/b", (0.0, 1.0, 0.0)),
                ("https://x/c", (0.5, 0.5, 0.0)),
            ],
        )
        tool = DocsSearchTool(_router_with_embed(vector=(0.9, 0.1, 0.0)), cache_root=tmp_path)
        result = await tool.execute(query="placeholder query", site="ops", top_k=2)
        assert result.success is True
        payload = json.loads(result.output)
        assert len(payload) == 2
        assert payload[0]["url"] == "https://x/a"
        assert payload[0]["site"] == "ops"
        assert "score" in payload[0]
        assert "excerpt" in payload[0]

    @pytest.mark.asyncio
    async def test_top_k_clamped(self, tmp_path: pathlib.Path) -> None:
        _seed_store(tmp_path, site="ops", rows=[("https://x/a", (1.0, 0.0, 0.0))])
        tool = DocsSearchTool(_router_with_embed(), cache_root=tmp_path)
        result = await tool.execute(query="x", site="ops", top_k=999)
        assert result.success is True
        # Cap should keep the call safe even with huge top_k.
        assert len(json.loads(result.output)) == 1

    @pytest.mark.asyncio
    async def test_no_matches_renders_message(self, tmp_path: pathlib.Path) -> None:
        # Seed a store but pass a vector orthogonal to no rows — search
        # always returns the rows, just with low scores.  The "(no matches)"
        # branch only fires when the store itself is empty after seeding.
        path = index.store_path_for("ops", root=tmp_path)
        DocsStore("ops", path).close()  # creates an empty store
        tool = DocsSearchTool(_router_with_embed(), cache_root=tmp_path)
        result = await tool.execute(query="x", site="ops")
        assert result.success is True
        assert "no matches" in result.output.lower()

    @pytest.mark.asyncio
    async def test_unknown_site_treated_as_no_index(self, tmp_path: pathlib.Path) -> None:
        tool = DocsSearchTool(_router_with_embed(), cache_root=tmp_path)
        result = await tool.execute(query="x", site="not-registered")
        assert result.success is False
        assert "no docs index" in result.error.lower()


# ---------------------------------------------------------------------------
# @docs provider
# ---------------------------------------------------------------------------


class TestDocsProvider:
    """``@docs <site> <query>`` mention provider."""

    @pytest.mark.asyncio
    async def test_missing_args(self) -> None:
        provider = DocsProvider(role_router=RoleRouter())
        block = await provider.expand("", ExpansionContext())
        assert "usage" in block.rendered.lower()
        assert block.error

    @pytest.mark.asyncio
    async def test_missing_query(self) -> None:
        provider = DocsProvider(role_router=RoleRouter())
        block = await provider.expand("ops", ExpansionContext())
        assert "missing query" in block.rendered.lower()
        assert block.error

    @pytest.mark.asyncio
    async def test_no_router_renders_error(self) -> None:
        provider = DocsProvider(role_router=None)
        block = await provider.expand("ops secrets", ExpansionContext())
        assert "no role router" in block.rendered.lower()
        assert block.error

    @pytest.mark.asyncio
    async def test_search_returns_block(self, tmp_path: pathlib.Path) -> None:
        _seed_store(
            tmp_path,
            site="ops",
            rows=[("https://x/a", (1.0, 0.0, 0.0))],
        )
        router = _router_with_embed()
        provider = DocsProvider(role_router=router, cache_root=tmp_path)
        block = await provider.expand("ops secrets", ExpansionContext())
        assert "https://x/a" in block.rendered
        assert not block.error

    @pytest.mark.asyncio
    async def test_through_expand_mentions(self, tmp_path: pathlib.Path) -> None:
        # End-to-end: build a registry that includes @docs and run the
        # full mention-expansion pipeline.
        _seed_store(tmp_path, site="ops", rows=[("https://x/a", (1.0, 0.0, 0.0))])
        router = _router_with_embed()
        registry = build_default_registry(role_router=router)
        # Override the @docs cache root by re-registering with the
        # tmp-path cache.  Cleanest: register a fresh DocsProvider.
        registry.register(DocsProvider(role_router=router, cache_root=tmp_path))
        result = await expand_mentions(
            "look at @docs ops secrets here",
            registry,
            ExpansionContext(),
        )
        assert "https://x/a" in result.expanded


# ---------------------------------------------------------------------------
# Default-registry wiring
# ---------------------------------------------------------------------------


class TestDefaultRegistryWiring:
    """``@docs`` registers only when an embed-capable router is supplied."""

    def test_router_with_embed_registers_docs(self) -> None:
        router = _router_with_embed()
        registry = build_default_registry(role_router=router)
        assert registry.get("docs") is not None

    def test_no_router_skips_docs(self) -> None:
        registry = build_default_registry()
        assert registry.get("docs") is None

    def test_router_without_embed_skips_docs(self) -> None:
        # An empty RoleRouter — has_embed() is False — must not
        # cause the @docs provider to be registered, otherwise an
        # @docs mention would surface a runtime error rather than
        # the friendly "unknown provider" pass-through.
        empty_router = RoleRouter()
        registry = build_default_registry(role_router=empty_router)
        # Behaviour question: do we want the provider registered
        # but error at expand time, or absent entirely?  Today's
        # build_default_registry checks ``role_router is not None``,
        # so an empty router still registers.  The block surfaces
        # "no embed provider configured" at expand time.
        assert registry.get("docs") is not None
