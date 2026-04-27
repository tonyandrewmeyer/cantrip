"""Web fetch tool for retrieving content from URLs."""

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

# Probe paths for llms.txt, tried in order.
_LLMS_TXT_PATHS = ("/.well-known/llms.txt", "/llms.txt")

# Timeout for llms.txt probes (keep it short — this is speculative).
_LLMS_TXT_PROBE_TIMEOUT = 5.0


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


# Session-level cache: domain → llms.txt URL (or None if unavailable).
# Populated lazily on first fetch to each domain.
_llms_txt_cache: dict[str, str | None] = {}


async def _probe_llms_txt(client: httpx.AsyncClient, url: str) -> str | None:
    """Check whether the domain of *url* has an llms.txt file.

    Probes ``/.well-known/llms.txt`` first, then ``/llms.txt``.
    Returns the URL of the llms.txt if found, else ``None``.
    Results are cached per domain for the session.
    """
    parsed = urllib.parse.urlparse(url)
    domain = f"{parsed.scheme}://{parsed.netloc}"

    if domain in _llms_txt_cache:
        return _llms_txt_cache[domain]

    for probe_path in _LLMS_TXT_PATHS:
        probe_url = domain + probe_path
        try:
            resp = await client.get(probe_url, timeout=_LLMS_TXT_PROBE_TIMEOUT)
            if resp.status_code == 200:
                ct = resp.headers.get("content-type", "")
                # Only accept text responses (not HTML error pages).
                if "text/plain" in ct or "text/markdown" in ct:
                    _llms_txt_cache[domain] = str(resp.url)
                    log.debug("Found llms.txt at %s", resp.url)
                    return _llms_txt_cache[domain]
        except (httpx.RequestError, httpx.TimeoutException):
            continue

    _llms_txt_cache[domain] = None
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
            " Automatically checks for llms.txt (LLM-friendly content) on first"
            " visit to each domain."
        )

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
                headers={"User-Agent": "Cantrip/0.1"},
            ) as client:
                # Probe for llms.txt on first visit to this domain.
                llms_url = await _probe_llms_txt(client, url)

                response = await _get_with_validated_redirects(client, url)
                response.raise_for_status()

                content_type = response.headers.get("content-type", "")
                text = response.text

                # If the response is HTML and llms.txt is available, fetch it
                # and use the LLM-friendly content instead.
                llms_content: str | None = None
                if llms_url and "text/html" in content_type:
                    llms_content = await _fetch_llms_txt(client, llms_url)

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
            text = f"[llms.txt content from {llms_url}]\n\n{llms_content}"
        elif extract_text and "text/html" in content_type:
            text = _strip_html(text)

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
            data["llms_txt_url"] = llms_url

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
