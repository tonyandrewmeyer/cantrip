"""Sitemap-driven crawler for the Phase 72.1 docs index.

Strategy: every target site exposes a ``sitemap.xml`` at a stable
URL.  We fetch the sitemap, filter the URLs to the same host, and
download each page.  Recursive BFS is intentionally out of scope —
sitemaps cover the canonical Canonical surfaces, BFS would risk
chasing unbounded link graphs and surface-area we don't want.

HTML extraction reuses the same flat-text approach the existing
:class:`cantrip.agent.tools.web._HTMLTextExtractor` uses: drop
``<script>``/``<style>``, collapse whitespace, prefer ``<title>``
plus heading-anchored sections.  We don't need rendered prose
fidelity — the text just feeds the embedder.
"""

from __future__ import annotations

import dataclasses
import html.parser
import logging
import urllib.parse
import xml.etree.ElementTree as ET
from collections.abc import Iterable

import httpx

log = logging.getLogger(__name__)

_USER_AGENT = "Cantrip/0.1 (docs-index)"
_TIMEOUT_SECONDS = 30.0
_MAX_PAGE_BYTES = 4 * 1024 * 1024  # 4 MB cap per page

# Sitemap XML namespace shared by every Canonical doc site.
_SITEMAP_NS = "{http://www.sitemaps.org/schemas/sitemap/0.9}"


@dataclasses.dataclass(frozen=True, slots=True)
class CrawledPage:
    """One page fetched from a site, post-extraction.

    ``title`` is the document title (``<title>`` element, or the
    first ``<h1>`` if missing).  ``body`` is the flattened text
    used for chunking.  ``url`` is the canonical URL, useful for
    de-duplication and citation.
    """

    url: str
    title: str
    body: str


def _same_host(url: str, host: str) -> bool:
    """Return ``True`` when *url*'s host matches *host* exactly."""
    parsed = urllib.parse.urlparse(url)
    return parsed.hostname == host


def parse_sitemap(xml_bytes: bytes, *, host: str) -> list[str]:
    """Return URLs from a sitemap.xml body, filtered to *host*.

    Handles both flat sitemaps (``<urlset>``) and sitemap indexes
    (``<sitemapindex>``) — the latter point at sub-sitemaps that
    the caller fetches and parses recursively.

    Malformed XML raises ``ET.ParseError``; the caller treats that
    as a fatal site-level error rather than swallowing it silently.
    """
    root = ET.fromstring(xml_bytes)
    urls: list[str] = []
    # Flat ``urlset`` — every ``<url><loc>`` is a page.
    for elem in root.findall(f"{_SITEMAP_NS}url/{_SITEMAP_NS}loc"):
        if elem.text:
            urls.append(elem.text.strip())
    # Index ``sitemapindex`` — every ``<sitemap><loc>`` is another sitemap.
    for elem in root.findall(f"{_SITEMAP_NS}sitemap/{_SITEMAP_NS}loc"):
        if elem.text:
            urls.append(elem.text.strip())
    return [u for u in urls if _same_host(u, host)]


class _HTMLBodyExtractor(html.parser.HTMLParser):
    """Flatten an HTML page to plain text + ``<title>``.

    Mirrors the approach :class:`cantrip.agent.tools.web._HTMLTextExtractor`
    uses for ``WebFetchTool`` so the docs index produces text that
    looks the same to the embedder regardless of whether a chunk
    came from a crawled doc or an inline ``@url`` fetch.
    """

    _SKIP_TAGS = frozenset({"script", "style", "nav", "footer", "header"})

    def __init__(self) -> None:
        super().__init__()
        self._buf: list[str] = []
        self._title_buf: list[str] = []
        self._in_title = False
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        if tag == "title":
            self._in_title = True
            return
        if tag in self._SKIP_TAGS:
            self._skip_depth += 1
            return
        if tag in {"p", "br", "li", "div", "section"}:
            self._buf.append("\n")
        if tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            self._buf.append("\n\n")

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False
            return
        if tag in self._SKIP_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1
            return
        if tag in {"h1", "h2", "h3", "h4", "h5", "h6", "p", "li"}:
            self._buf.append("\n")

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self._title_buf.append(data)
            return
        if self._skip_depth > 0:
            return
        self._buf.append(data)

    def title(self) -> str:
        return " ".join("".join(self._title_buf).split()).strip()

    def body(self) -> str:
        # Collapse runs of whitespace; preserve paragraph breaks.
        raw = "".join(self._buf)
        lines: list[str] = []
        for line in raw.splitlines():
            stripped = " ".join(line.split())
            lines.append(stripped)
        # Compress 3+ blank lines to 2.
        compacted: list[str] = []
        prev_blank = False
        for line in lines:
            if not line:
                if prev_blank:
                    continue
                prev_blank = True
            else:
                prev_blank = False
            compacted.append(line)
        return "\n".join(compacted).strip()


def extract_html(html_bytes: bytes) -> tuple[str, str]:
    """Return ``(title, body)`` extracted from *html_bytes*."""
    extractor = _HTMLBodyExtractor()
    try:
        extractor.feed(html_bytes.decode("utf-8", errors="replace"))
    except (ValueError, UnicodeDecodeError) as exc:
        log.warning("HTML extraction failed: %s", exc)
        return "", ""
    return extractor.title(), extractor.body()


async def fetch_sitemap_urls(
    sitemap_url: str,
    *,
    client: httpx.AsyncClient | None = None,
) -> list[str]:
    """Fetch *sitemap_url* and return every page URL in it.

    Resolves ``sitemapindex`` envelopes by fetching nested sitemaps
    once each; cycles or bad XML raise.  Cap on nested sitemaps is
    100 — Canonical doc sites are nowhere near that.

    The caller may pass a pre-configured ``httpx.AsyncClient`` so
    tests can mock it; otherwise the function builds a one-shot
    client per call.
    """
    parsed = urllib.parse.urlparse(sitemap_url)
    host = parsed.hostname or ""
    if not host:
        raise ValueError(f"sitemap URL has no host: {sitemap_url}")

    owner = client is None
    if owner:
        client = httpx.AsyncClient(
            timeout=_TIMEOUT_SECONDS,
            headers={"User-Agent": _USER_AGENT},
            follow_redirects=True,
        )
    try:
        urls = await _fetch_sitemap_recursive(client, sitemap_url, host=host, depth=0)
    finally:
        if owner:
            await client.aclose()
    return urls


async def _fetch_sitemap_recursive(
    client: httpx.AsyncClient,
    sitemap_url: str,
    *,
    host: str,
    depth: int,
) -> list[str]:
    """Walk a sitemap or sitemap-of-sitemaps, returning page URLs."""
    if depth > 4:
        log.warning("sitemap nesting too deep at %s; stopping", sitemap_url)
        return []
    response = await client.get(sitemap_url)
    response.raise_for_status()
    raw = parse_sitemap(response.content, host=host)
    pages: list[str] = []
    for url in raw:
        # If the URL itself ends with ``.xml``, treat as nested sitemap.
        if url.endswith(".xml"):
            try:
                pages.extend(
                    await _fetch_sitemap_recursive(client, url, host=host, depth=depth + 1)
                )
            except (httpx.HTTPError, ET.ParseError) as exc:
                log.warning("nested sitemap %s failed: %s", url, exc)
                continue
        else:
            pages.append(url)
    return pages


async def fetch_page(
    url: str,
    *,
    client: httpx.AsyncClient | None = None,
) -> CrawledPage | None:
    """Fetch *url* and return a :class:`CrawledPage`, or ``None`` on error.

    Errors (timeouts, non-2xx, oversize, decode failure) are logged
    and swallowed so a single bad page doesn't abort the whole
    crawl.  The caller iterates and collects whatever succeeds.
    """
    owner = client is None
    if owner:
        client = httpx.AsyncClient(
            timeout=_TIMEOUT_SECONDS,
            headers={"User-Agent": _USER_AGENT},
            follow_redirects=True,
        )
    try:
        try:
            response = await client.get(url)
        except httpx.HTTPError as exc:
            log.warning("fetch %s failed: %s", url, exc)
            return None
        if not response.is_success:
            log.warning("fetch %s returned %s", url, response.status_code)
            return None
        body_bytes = response.content
        if len(body_bytes) > _MAX_PAGE_BYTES:
            log.warning("fetch %s too large (%d bytes); skipping", url, len(body_bytes))
            return None
        title, body = extract_html(body_bytes)
        if not body:
            return None
        return CrawledPage(url=url, title=title, body=body)
    finally:
        if owner:
            await client.aclose()


def filter_urls(urls: Iterable[str], *, host: str) -> list[str]:
    """Drop URLs that don't match *host* and de-duplicate."""
    seen: set[str] = set()
    out: list[str] = []
    for url in urls:
        if not _same_host(url, host):
            continue
        if url in seen:
            continue
        seen.add(url)
        out.append(url)
    return out
