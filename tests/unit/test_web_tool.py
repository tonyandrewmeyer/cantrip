"""Tests for the web fetch tool."""

from unittest.mock import AsyncMock, patch

import httpx
import pytest

from cantrip.agent.tools.web import MAX_RESPONSE_CHARS, WebFetchTool, _strip_html


class TestStripHTML:
    """Tests for the _strip_html helper."""

    def test_removes_tags(self):
        assert _strip_html("<p>hello</p>") == "hello"

    def test_removes_script_content(self):
        html = "<p>before</p><script>alert('xss')</script><p>after</p>"
        assert _strip_html(html) == "before after"

    def test_removes_style_content(self):
        html = "<style>body { color: red; }</style><p>visible</p>"
        assert _strip_html(html) == "visible"

    def test_preserves_visible_text(self):
        html = (
            "<html><head><title>Title</title></head>"
            "<body><h1>Heading</h1><p>Paragraph</p></body></html>"
        )
        result = _strip_html(html)
        assert "Title" in result
        assert "Heading" in result
        assert "Paragraph" in result

    def test_collapses_whitespace(self):
        html = "<p>  lots   of    spaces  </p>"
        assert _strip_html(html) == "lots of spaces"


def _make_response(
    *,
    status_code: int = 200,
    text: str = "",
    content_type: str = "text/plain",
    url: str = "https://example.com",
) -> httpx.Response:
    """Build a minimal httpx.Response for testing."""
    response = httpx.Response(
        status_code=status_code,
        headers={"content-type": content_type},
        text=text,
        request=httpx.Request("GET", url),
    )
    return response


class TestWebFetchTool:
    """Tests for WebFetchTool."""

    @pytest.fixture
    def tool(self):
        return WebFetchTool()

    @pytest.mark.asyncio
    async def test_fetch_plain_text(self, tool):
        """Plain text content is returned as-is."""
        resp = _make_response(text="hello world", content_type="text/plain")
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("cantrip.agent.tools.web.httpx.AsyncClient", return_value=mock_client):
            result = await tool.execute(url="https://example.com/file.txt")

        assert result.success
        assert result.output == "hello world"
        assert result.data["status_code"] == 200
        assert result.data["content_type"] == "text/plain"
        assert result.data["truncated"] is False

    @pytest.mark.asyncio
    async def test_fetch_html_extract_text(self, tool):
        """HTML content is stripped when extract_text is True."""
        html = "<html><body><p>Hello</p><script>bad();</script></body></html>"
        resp = _make_response(text=html, content_type="text/html; charset=utf-8")
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("cantrip.agent.tools.web.httpx.AsyncClient", return_value=mock_client):
            result = await tool.execute(url="https://example.com", extract_text=True)

        assert result.success
        assert "Hello" in result.output
        assert "<p>" not in result.output
        assert "bad()" not in result.output

    @pytest.mark.asyncio
    async def test_fetch_html_raw(self, tool):
        """HTML content is returned raw when extract_text is False."""
        html = "<html><body><p>Hello</p></body></html>"
        resp = _make_response(text=html, content_type="text/html")
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("cantrip.agent.tools.web.httpx.AsyncClient", return_value=mock_client):
            result = await tool.execute(url="https://example.com", extract_text=False)

        assert result.success
        assert "<p>Hello</p>" in result.output

    @pytest.mark.asyncio
    async def test_http_error(self, tool):
        """HTTP errors produce a failed ToolResult with status info."""
        resp = _make_response(status_code=404, text="Not Found")
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        # raise_for_status() raises on non-2xx.
        resp.raise_for_status = lambda: (_ for _ in ()).throw(
            httpx.HTTPStatusError(
                "Not Found",
                request=resp.request,
                response=resp,
            )
        )

        with patch("cantrip.agent.tools.web.httpx.AsyncClient", return_value=mock_client):
            result = await tool.execute(url="https://example.com/missing")

        assert not result.success
        assert "404" in result.error
        assert result.data["status_code"] == 404

    @pytest.mark.asyncio
    async def test_timeout(self, tool):
        """Timeout produces a clear error message."""
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=httpx.TimeoutException("timed out"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("cantrip.agent.tools.web.httpx.AsyncClient", return_value=mock_client):
            result = await tool.execute(url="https://slow.example.com")

        assert not result.success
        assert "timed out" in result.error.lower()

    @pytest.mark.asyncio
    async def test_connection_error(self, tool):
        """Connection errors produce a failed ToolResult."""
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=httpx.ConnectError("Connection refused"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("cantrip.agent.tools.web.httpx.AsyncClient", return_value=mock_client):
            result = await tool.execute(url="https://down.example.com")

        assert not result.success
        assert "connection error" in result.error.lower()

    @pytest.mark.asyncio
    async def test_large_response_truncated(self, tool):
        """Responses larger than MAX_RESPONSE_CHARS are truncated."""
        big_text = "x" * (MAX_RESPONSE_CHARS + 500)
        resp = _make_response(text=big_text, content_type="text/plain")
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("cantrip.agent.tools.web.httpx.AsyncClient", return_value=mock_client):
            result = await tool.execute(url="https://example.com/big")

        assert result.success
        assert len(result.output) == MAX_RESPONSE_CHARS
        assert result.data["truncated"] is True
