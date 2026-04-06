"""Web fetch tool for retrieving content from URLs."""

import html.parser
import ipaddress
import socket
import urllib.parse
from typing import Any

import httpx

from cantrip.agent.tools.base import Tool, ToolResult

# Hostnames that resolve to cloud metadata services.
_METADATA_HOSTNAMES = frozenset({
    "metadata.google.internal",
    "instance-data.ec2.internal",
})


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

# Tags whose content should be discarded entirely when stripping HTML.
_SKIP_TAGS = frozenset({"script", "style"})


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
            async with httpx.AsyncClient(
                timeout=30.0,
                follow_redirects=True,
                headers={"User-Agent": "Cantrip/0.1"},
            ) as client:
                response = await client.get(url)
                response.raise_for_status()
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

        content_type = response.headers.get("content-type", "")
        text = response.text

        if extract_text and "text/html" in content_type:
            text = _strip_html(text)

        truncated = len(text) > MAX_RESPONSE_CHARS
        if truncated:
            text = text[:MAX_RESPONSE_CHARS]

        return ToolResult(
            success=True,
            output=text,
            data={
                "status_code": response.status_code,
                "content_type": content_type,
                "url": str(response.url),
                "truncated": truncated,
            },
        )
