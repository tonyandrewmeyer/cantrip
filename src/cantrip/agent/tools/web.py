"""Web fetch tool for retrieving content from URLs."""

import dataclasses
import html.parser
import ipaddress
import logging
import socket
import urllib.parse
from typing import Any

import httpx

from cantrip.agent.tools.base import Tool, ToolResult

log = logging.getLogger(__name__)

# Hostnames that resolve to cloud metadata services.
_METADATA_HOSTNAMES = frozenset(
    {
        "metadata.google.internal",
        "instance-data.ec2.internal",
    }
)


def _is_private_url(url: str) -> str | None:
    """Return a reason string if *url* targets a private or internal resource, else ``None``."""
    parsed = urllib.parse.urlparse(url)
    hostname = parsed.hostname or ""

    # Block cloud metadata IP and hostnames.
    if hostname in _METADATA_HOSTNAMES:
        return "URL targets a cloud metadata endpoint"

    # Resolve hostname to IP addresses and check each one.
    try:
        addr_info = socket.getaddrinfo(hostname, None, proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        # Cannot resolve — let httpx handle the error later.
        return None

    for _family, _type, _proto, _canonname, sockaddr in addr_info:
        ip_str = sockaddr[0]
        try:
            addr = ipaddress.ip_address(ip_str)
        except ValueError:
            continue
        if addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved:
            return f"URL resolves to a private/internal address ({ip_str})"

    return None


# Truncate responses beyond this to avoid blowing up LLM context.
MAX_RESPONSE_CHARS = 100_000

# Maximum redirect hops before we give up — matches httpx's own default.
# Each hop is re-validated by :func:`_is_private_url` so a public URL
# can't 302-bounce into AWS metadata or a LAN host.
_MAX_REDIRECTS = 10

# Tags whose content should be discarded entirely when stripping HTML.
_SKIP_TAGS = frozenset({"script", "style"})

# Probe paths for the llms.txt convention, tried in order.  ``llms.txt``
# is the curated index of markdown URLs; ``llms-full.txt`` is the full
# concatenated corpus.  ``/.well-known/`` is the IETF-blessed location
# but in practice most sites ship the file at the root, so we try both.
_LLMS_INDEX_PATHS = ("/.well-known/llms.txt", "/llms.txt")
_LLMS_FULL_PATHS = ("/.well-known/llms-full.txt", "/llms-full.txt")

# Timeout for llms.txt probes (keep it short — this is speculative).
_LLMS_TXT_PROBE_TIMEOUT = 5.0

# Accept header sent on every fetch.  Servers that honour content
# negotiation (Mintlify, Anthropic docs, GitHub raw, …) return markdown
# directly when asked, so we never need to strip HTML or substitute
# llms.txt for those pages.  ``*/*`` keeps non-text endpoints happy.
_ACCEPT_HEADER = "text/markdown, text/plain;q=0.9, text/html;q=0.5, */*;q=0.1"


class _HTMLTextExtractor(html.parser.HTMLParser):
    """HTMLParser subclass that extracts visible text from HTML."""

    def __init__(self) -> None:
        super().__init__()
        self._pieces: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, _attrs: list[tuple[str, str | None]]) -> None:
        if tag in _SKIP_TAGS:
            self._skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0:
            self._pieces.append(data)

    def get_text(self) -> str:
        """Return the collected visible text, with runs of whitespace collapsed."""
        raw = " ".join(self._pieces)
        # Collapse runs of whitespace into single spaces, then strip.
        return " ".join(raw.split())


def _strip_html(content: str) -> str:
    """Strip HTML tags and return visible text."""
    extractor = _HTMLTextExtractor()
    extractor.feed(content)
    return extractor.get_text()


@dataclasses.dataclass(frozen=True)
class _LlmsTxtUrls:
    """Resolved URLs for the llms.txt artefacts on a domain.

    Either field can be ``None`` if the corresponding probe came back
    empty.  An instance with both fields ``None`` is a successful "this
    domain has no llms.txt-family files" cache entry.
    """

    index: str | None = None
    full: str | None = None


# Session-level cache: domain → discovered llms.txt URLs.  Populated
# lazily on first fetch to each domain.
_llms_txt_cache: dict[str, _LlmsTxtUrls] = {}


async def _probe_llms_txt(client: httpx.AsyncClient, url: str) -> _LlmsTxtUrls:
    """Discover llms.txt and llms-full.txt URLs for the domain of *url*.

    Probes the ``/.well-known/`` location then the bare path for each of
    ``llms.txt`` (the curated index) and ``llms-full.txt`` (the full
    corpus).  Results are cached per domain for the session.
    """
    parsed = urllib.parse.urlparse(url)
    domain = f"{parsed.scheme}://{parsed.netloc}"

    cached = _llms_txt_cache.get(domain)
    if cached is not None:
        return cached

    index_url = await _probe_first_match(client, domain, _LLMS_INDEX_PATHS)
    full_url = await _probe_first_match(client, domain, _LLMS_FULL_PATHS)
    result = _LlmsTxtUrls(index=index_url, full=full_url)
    _llms_txt_cache[domain] = result
    return result


async def _probe_first_match(
    client: httpx.AsyncClient,
    domain: str,
    paths: tuple[str, ...],
) -> str | None:
    """Return the first probe path that yields ``200 text/markdown|plain``."""
    for probe_path in paths:
        probe_url = domain + probe_path
        try:
            resp = await client.get(probe_url, timeout=_LLMS_TXT_PROBE_TIMEOUT)
            if resp.status_code == 200:
                ct = resp.headers.get("content-type", "")
                # Only accept text responses (not HTML error pages).
                if "text/plain" in ct or "text/markdown" in ct:
                    log.debug("Found llms artefact at %s", resp.url)
                    return str(resp.url)
        except (httpx.RequestError, httpx.TimeoutException):
            continue
    return None


async def _fetch_llms_txt(client: httpx.AsyncClient, llms_url: str) -> str | None:
    """Fetch the content of an llms.txt file.  Returns ``None`` on failure."""
    try:
        resp = await client.get(llms_url)
        if resp.status_code == 200:
            return resp.text
    except (httpx.RequestError, httpx.TimeoutException):
        pass
    return None


def clear_llms_txt_cache() -> None:
    """Clear the domain → llms.txt cache.  Useful for testing."""
    _llms_txt_cache.clear()


class _SSRFRedirectError(Exception):
    """Raised when a redirect chain points at a private/internal address."""

    def __init__(self, hop_url: str, reason: str) -> None:
        super().__init__(f"redirect to {hop_url} blocked: {reason}")
        self.hop_url = hop_url
        self.reason = reason


async def _get_with_validated_redirects(
    client: httpx.AsyncClient,
    url: str,
) -> httpx.Response:
    """Fetch *url*, walking redirects manually so each hop is SSRF-checked.

    httpx's ``follow_redirects=True`` only validates the *first* URL.
    A public URL that returns ``302 Location: http://169.254.169.254/...``
    (AWS metadata) or ``http://192.168.1.1/admin`` would leak the
    response back into the LLM's context.  Resolve and re-validate
    every hop, including relative ``Location`` headers, before
    issuing the next request.

    Caller has already validated *url*; this helper handles every
    subsequent hop.  Raises :class:`_SSRFRedirectError` if a hop
    targets a private destination.
    """
    current_url = url
    for _ in range(_MAX_REDIRECTS + 1):
        response = await client.get(current_url)
        if not response.is_redirect:
            return response
        location = response.headers.get("Location")
        if not location:
            return response
        # ``Location`` may be relative — resolve against the current URL
        # so the SSRF check sees a fully-qualified target.
        next_url = str(httpx.URL(response.url).join(location))
        reason = _is_private_url(next_url)
        if reason is not None:
            raise _SSRFRedirectError(next_url, reason)
        current_url = next_url
    # Out of hops; surface httpx's own error so callers see something
    # consistent with what ``follow_redirects=True`` would have raised.
    raise httpx.TooManyRedirects(
        f"exceeded {_MAX_REDIRECTS} redirect hops fetching {url}",
        request=response.request,
    )


class WebFetchTool(Tool):
    """Tool to fetch content from a URL."""

    @property
    def name(self) -> str:
        return "web_fetch"

    @property
    def description(self) -> str:
        return (
            "Fetch content from a URL. Useful for reading documentation, source code,"
            " Charmhub pages, PyPI packages, and GitHub repositories."
            " Sends ``Accept: text/markdown`` so servers that support content"
            " negotiation return markdown directly, and probes for llms.txt /"
            " llms-full.txt on first visit to each domain."
        )

    def intro_caption(self, arguments: dict[str, Any]) -> str | None:
        url = arguments.get("url")
        if not url:
            return None
        try:
            host = urllib.parse.urlparse(str(url)).hostname or str(url)
        except (ValueError, TypeError):
            host = str(url)
        return f"Fetching {host}…"

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "The URL to fetch.",
                },
                "extract_text": {
                    "type": "boolean",
                    "description": (
                        "If true (the default), strip HTML tags and return plain text."
                        " Set to false to return raw HTML."
                    ),
                    "default": True,
                },
            },
            "required": ["url"],
        }

    async def execute(self, url: str, extract_text: bool = True) -> ToolResult:
        """Fetch content from *url*."""
        if not url.startswith(("http://", "https://")):
            return ToolResult(
                success=False,
                output="",
                error=f"Only http:// and https:// URLs are supported, got: {url[:50]}",
            )

        reason = _is_private_url(url)
        if reason:
            return ToolResult(
                success=False,
                output="",
                error=f"Blocked: {reason}",
            )
        try:
            # ``follow_redirects=False`` is deliberate — we walk redirects
            # ourselves through :func:`_get_with_validated_redirects` so
            # each hop is re-checked against :func:`_is_private_url`.
            async with httpx.AsyncClient(
                timeout=30.0,
                follow_redirects=False,
                headers={
                    "User-Agent": "Cantrip/0.1",
                    "Accept": _ACCEPT_HEADER,
                },
            ) as client:
                # Probe for llms.txt / llms-full.txt on first visit to this domain.
                llms_urls = await _probe_llms_txt(client, url)

                response = await _get_with_validated_redirects(client, url)
                response.raise_for_status()

                content_type = response.headers.get("content-type", "")
                text = response.text

                # If content negotiation already returned markdown / plain text
                # there's nothing to substitute — skip the llms.txt fetch.
                # Only fall back to the llms.txt index when the server gave us
                # HTML, which is what the substitution exists to soften.
                llms_content: str | None = None
                if llms_urls.index and "text/html" in content_type:
                    llms_content = await _fetch_llms_txt(client, llms_urls.index)

        except _SSRFRedirectError as exc:
            return ToolResult(
                success=False,
                output="",
                error=f"Blocked: {exc}",
            )
        except httpx.TimeoutException:
            return ToolResult(
                success=False,
                output="",
                error=f"Request timed out fetching {url}",
            )
        except httpx.HTTPStatusError as exc:
            return ToolResult(
                success=False,
                output="",
                error=f"HTTP {exc.response.status_code} fetching {url}",
                data={"status_code": exc.response.status_code, "url": url},
            )
        except httpx.RequestError as exc:
            return ToolResult(
                success=False,
                output="",
                error=f"Connection error fetching {url}: {exc}",
            )

        if llms_content:
            text = f"[llms.txt content from {llms_urls.index}]\n\n{llms_content}"
        elif extract_text and "text/html" in content_type:
            text = _strip_html(text)
        # Markdown / plain text passes through unchanged — content negotiation
        # already gave us the LLM-friendly representation.

        truncated = len(text) > MAX_RESPONSE_CHARS
        if truncated:
            text = text[:MAX_RESPONSE_CHARS]

        data: dict[str, Any] = {
            "status_code": response.status_code,
            "content_type": content_type,
            "url": str(response.url),
            "truncated": truncated,
        }
        if llms_content:
            data["llms_txt_url"] = llms_urls.index
        # Always surface the llms-full.txt URL when discovered so the agent
        # can fetch the full corpus explicitly on a subsequent call.
        if llms_urls.full:
            data["llms_full_txt_url"] = llms_urls.full

        # Strip protocol/scheme from caption for readability.
        display_url = str(response.url)
        for prefix in ("https://", "http://"):
            if display_url.startswith(prefix):
                display_url = display_url[len(prefix) :]
                break
        if len(display_url) > 60:
            display_url = display_url[:59] + "…"
        return ToolResult(
            success=True,
            output=text,
            data=data,
            caption=f"Fetched {display_url} ({len(text)} bytes)",
        )
