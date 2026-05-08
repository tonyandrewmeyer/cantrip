"""Phase 72.1 — crawler + indexer pipeline (sites, crawl, index)."""

from __future__ import annotations

import pathlib
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from cantrip.docs_index import crawl, index, sites
from cantrip.docs_index.store import DocsStore
from tests.support.roles import StubEmbed as _StubEmbed

# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------


_TEST_SITE = sites.DocSite(
    name="testdocs",
    home_url="https://docs.example/",
    sitemap_url="https://docs.example/sitemap.xml",
    description="fixture site",
)


# ---------------------------------------------------------------------------
# Site registry
# ---------------------------------------------------------------------------


class TestSiteRegistry:
    """The static registry shipped with Cantrip."""

    def test_six_sites_registered(self) -> None:
        # The roadmap calls for six canonical surfaces.
        assert len(sites.SITES) == 6
        # Order is stable for ``cantrip docs list``.
        assert sites.names()[:2] == ("juju", "ops")

    def test_by_name_lookup(self) -> None:
        site = sites.by_name("ops")
        assert site is not None
        assert site.name == "ops"
        assert "documentation.ubuntu.com/ops" in site.sitemap_url

    def test_by_name_unknown(self) -> None:
        assert sites.by_name("not-a-site") is None

    def test_by_name_case_insensitive(self) -> None:
        assert sites.by_name("OPS") is sites.by_name("ops")


# ---------------------------------------------------------------------------
# Crawl helpers
# ---------------------------------------------------------------------------


_FLAT_SITEMAP = b"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://docs.example/page-one</loc></url>
  <url><loc>https://docs.example/page-two</loc></url>
  <url><loc>https://other-host/page-three</loc></url>
</urlset>
"""

_INDEX_SITEMAP = b"""<?xml version="1.0" encoding="UTF-8"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <sitemap><loc>https://docs.example/sitemap-pages.xml</loc></sitemap>
</sitemapindex>
"""

_NESTED_SITEMAP = b"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://docs.example/nested-one</loc></url>
</urlset>
"""

_SAMPLE_HTML = b"""<!doctype html>
<html><head><title>Hello Doc</title></head>
<body>
  <h1>Heading</h1>
  <p>First paragraph with some words.</p>
  <p>Second paragraph for the test.</p>
  <script>noisy()</script>
</body></html>
"""


class TestParseSitemap:
    """``parse_sitemap`` filters and de-namespaces correctly."""

    def test_flat_sitemap_filters_to_host(self) -> None:
        urls = crawl.parse_sitemap(_FLAT_SITEMAP, host="docs.example")
        assert urls == [
            "https://docs.example/page-one",
            "https://docs.example/page-two",
        ]

    def test_index_sitemap_returns_nested_locations(self) -> None:
        urls = crawl.parse_sitemap(_INDEX_SITEMAP, host="docs.example")
        # The caller is responsible for following the nested locations.
        assert urls == ["https://docs.example/sitemap-pages.xml"]


class TestExtractHtml:
    """HTML body extraction strips scripts and preserves structure."""

    def test_extracts_title_and_body(self) -> None:
        title, body = crawl.extract_html(_SAMPLE_HTML)
        assert title == "Hello Doc"
        assert "First paragraph" in body
        assert "Second paragraph" in body
        # Script content is dropped.
        assert "noisy" not in body
        # Heading appears.
        assert "Heading" in body

    def test_handles_invalid_input_gracefully(self) -> None:
        title, body = crawl.extract_html(b"\xff\xfe\x00broken")
        # Non-UTF-8 bytes don't crash; result may be empty.
        assert isinstance(title, str)
        assert isinstance(body, str)


class TestFilterUrls:
    """De-duplication and host filter."""

    def test_strips_other_hosts(self) -> None:
        urls = [
            "https://docs.example/a",
            "https://other-host/b",
            "https://docs.example/a",  # duplicate
            "https://docs.example/c",
        ]
        out = crawl.filter_urls(urls, host="docs.example")
        assert out == [
            "https://docs.example/a",
            "https://docs.example/c",
        ]


# ---------------------------------------------------------------------------
# Indexer end-to-end
# ---------------------------------------------------------------------------


def _mock_response(content: bytes, *, content_type: str = "text/html") -> httpx.Response:
    """Build a synthetic httpx.Response without going through a transport."""
    return httpx.Response(
        200,
        content=content,
        headers={"content-type": content_type},
        request=httpx.Request("GET", "https://x/"),
    )


class TestIndexSite:
    """End-to-end: crawl one fixture page, embed, store, search."""

    @pytest.mark.asyncio
    async def test_index_with_url_filter(self, tmp_path: pathlib.Path) -> None:
        # Pre-build the store so we can read it back after the run.
        store = DocsStore(_TEST_SITE.name, tmp_path / "ops" / "index.db")
        embed = _StubEmbed()

        async def _fetch(_url: str, **_kwargs) -> httpx.Response:
            return _mock_response(_SAMPLE_HTML)

        with patch("cantrip.docs_index.crawl.httpx.AsyncClient") as mock_client:
            instance = AsyncMock()
            instance.get.side_effect = _fetch
            instance.__aenter__ = AsyncMock(return_value=instance)
            instance.__aexit__ = AsyncMock(return_value=False)
            mock_client.return_value = instance
            report = await index.index_site(
                _TEST_SITE,
                embed,
                url_filter=["https://docs.example/page-one"],
                store=store,
            )

        assert report.site == "testdocs"
        assert report.pages_crawled == 1
        assert report.chunks_indexed >= 1
        assert report.embed_calls >= 1
        # The embed provider was actually called.
        assert embed.calls
        # The store now contains the chunks.
        assert store.count() == report.chunks_indexed
        # Search returns the page we indexed.
        hits = store.search((0.0, 1.0, 2.0), top_k=1)
        assert hits[0].url == "https://docs.example/page-one"
        assert hits[0].title == "Hello Doc"

    @pytest.mark.asyncio
    async def test_failed_pages_become_errors(self, tmp_path: pathlib.Path) -> None:
        store = DocsStore(_TEST_SITE.name, tmp_path / "ops" / "index.db")
        embed = _StubEmbed()

        async def _fetch(url: str, **_kwargs) -> httpx.Response:
            return httpx.Response(
                404,
                content=b"missing",
                request=httpx.Request("GET", url),
            )

        with patch("cantrip.docs_index.crawl.httpx.AsyncClient") as mock_client:
            instance = AsyncMock()
            instance.get.side_effect = _fetch
            instance.__aenter__ = AsyncMock(return_value=instance)
            instance.__aexit__ = AsyncMock(return_value=False)
            mock_client.return_value = instance
            report = await index.index_site(
                _TEST_SITE,
                embed,
                url_filter=["https://docs.example/missing"],
                store=store,
            )
        assert report.pages_crawled == 0
        assert "https://docs.example/missing" in report.errors
        assert store.count() == 0

    @pytest.mark.asyncio
    async def test_reindex_replaces_chunks(self, tmp_path: pathlib.Path) -> None:
        store = DocsStore(_TEST_SITE.name, tmp_path / "ops" / "index.db")
        embed = _StubEmbed()

        async def _fetch(_url: str, **_kwargs) -> httpx.Response:
            return _mock_response(_SAMPLE_HTML)

        with patch("cantrip.docs_index.crawl.httpx.AsyncClient") as mock_client:
            instance = AsyncMock()
            instance.get.side_effect = _fetch
            instance.__aenter__ = AsyncMock(return_value=instance)
            instance.__aexit__ = AsyncMock(return_value=False)
            mock_client.return_value = instance
            await index.index_site(
                _TEST_SITE,
                embed,
                url_filter=["https://docs.example/page-one"],
                store=store,
            )
            count_after_first = store.count()
            await index.index_site(
                _TEST_SITE,
                embed,
                url_filter=["https://docs.example/page-one"],
                store=store,
            )
            count_after_second = store.count()

        # Re-indexing the same page does not double the rows.
        assert count_after_second == count_after_first


class TestStorePathFor:
    """Cache directory layout."""

    def test_path_uses_site_name(self, tmp_path: pathlib.Path) -> None:
        path = index.store_path_for("juju", root=tmp_path)
        assert path == tmp_path / "juju" / "index.db"
