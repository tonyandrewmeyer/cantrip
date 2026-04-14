"""Tests for the web fetch tool."""

from unittest.mock import AsyncMock, patch

import httpx
import pytest

from cantrip.agent.tools.web import (
    MAX_RESPONSE_CHARS,
    WebFetchTool,
    _strip_html,
    clear_llms_txt_cache,
)


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

    @pytest.fixture(autouse=True)
    def _clear_cache(self):
        """Clear the llms.txt cache before each test."""
        clear_llms_txt_cache()
        yield
        clear_llms_txt_cache()

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


class TestLlmsTxtAwareness:
    """Tests for llms.txt probing and preference."""

    @pytest.fixture(autouse=True)
    def _clear_cache(self):
        """Clear the llms.txt cache before each test."""
        clear_llms_txt_cache()
        yield
        clear_llms_txt_cache()

    @pytest.fixture
    def tool(self):
        return WebFetchTool()

    @pytest.mark.asyncio
    async def test_llms_txt_preferred_over_html(self, tool):
        """When llms.txt exists, its content replaces stripped HTML."""
        llms_resp = _make_response(
            text="# LLM-friendly docs\nThis is great content.",
            content_type="text/plain",
            url="https://example.com/.well-known/llms.txt",
        )
        html_resp = _make_response(
            text="<html><body><p>Normal HTML</p></body></html>",
            content_type="text/html",
            url="https://example.com/docs",
        )

        async def mock_get(url, **_kwargs):
            url_str = str(url)
            if "llms.txt" in url_str:
                return llms_resp
            return html_resp

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=mock_get)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("cantrip.agent.tools.web.httpx.AsyncClient", return_value=mock_client):
            result = await tool.execute(url="https://example.com/docs")

        assert result.success
        assert "LLM-friendly docs" in result.output
        assert "Normal HTML" not in result.output
        assert result.data["llms_txt_url"] == "https://example.com/.well-known/llms.txt"

    @pytest.mark.asyncio
    async def test_llms_txt_fallback_path(self, tool):
        """Falls back to /llms.txt if /.well-known/llms.txt is 404."""
        not_found_resp = _make_response(
            status_code=404,
            text="Not Found",
            content_type="text/html",
            url="https://example.com/.well-known/llms.txt",
        )
        fallback_resp = _make_response(
            text="# Fallback llms.txt",
            content_type="text/plain",
            url="https://example.com/llms.txt",
        )
        html_resp = _make_response(
            text="<html><body>Page</body></html>",
            content_type="text/html",
            url="https://example.com/",
        )

        async def mock_get(url, **_kwargs):
            url_str = str(url)
            if url_str == "https://example.com/.well-known/llms.txt":
                return not_found_resp
            if url_str == "https://example.com/llms.txt":
                return fallback_resp
            return html_resp

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=mock_get)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("cantrip.agent.tools.web.httpx.AsyncClient", return_value=mock_client):
            result = await tool.execute(url="https://example.com/")

        assert result.success
        assert "Fallback llms.txt" in result.output

    @pytest.mark.asyncio
    async def test_no_llms_txt_falls_through(self, tool):
        """When no llms.txt exists, normal HTML stripping applies."""
        not_found_resp = _make_response(
            status_code=404,
            text="Not Found",
            content_type="text/html",
            url="https://example.com/.well-known/llms.txt",
        )
        html_resp = _make_response(
            text="<html><body><p>Normal content</p></body></html>",
            content_type="text/html",
            url="https://example.com/",
        )

        async def mock_get(url, **_kwargs):
            url_str = str(url)
            if "llms.txt" in url_str:
                return not_found_resp
            return html_resp

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=mock_get)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("cantrip.agent.tools.web.httpx.AsyncClient", return_value=mock_client):
            result = await tool.execute(url="https://example.com/")

        assert result.success
        assert "Normal content" in result.output
        assert "llms_txt_url" not in result.data

    @pytest.mark.asyncio
    async def test_cache_avoids_repeated_probes(self, tool):
        """Second fetch to the same domain reuses the cached probe result."""
        llms_resp = _make_response(
            text="# Cached content",
            content_type="text/plain",
            url="https://example.com/.well-known/llms.txt",
        )
        html_resp = _make_response(
            text="<html><body>Page</body></html>",
            content_type="text/html",
            url="https://example.com/page",
        )

        call_count = 0

        async def mock_get(url, **_kwargs):
            nonlocal call_count
            url_str = str(url)
            if "llms.txt" in url_str:
                call_count += 1
                return llms_resp
            return html_resp

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=mock_get)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("cantrip.agent.tools.web.httpx.AsyncClient", return_value=mock_client):
            await tool.execute(url="https://example.com/page1")
            await tool.execute(url="https://example.com/page2")

        # The probe should only happen once; the second fetch uses the cache.
        # call_count tracks llms.txt GET requests (probe + content fetches).
        # First request: 1 probe + 1 content fetch = 2.
        # Second request: 0 probes + 1 content fetch = 1.
        # Total llms.txt GETs = 3.
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_llms_txt_not_used_for_plain_text(self, tool):
        """llms.txt content is only substituted for HTML responses."""
        llms_resp = _make_response(
            text="# LLM docs",
            content_type="text/plain",
            url="https://example.com/.well-known/llms.txt",
        )
        plain_resp = _make_response(
            text="Plain text response",
            content_type="text/plain",
            url="https://example.com/api/data",
        )

        async def mock_get(url, **_kwargs):
            url_str = str(url)
            if "llms.txt" in url_str:
                return llms_resp
            return plain_resp

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=mock_get)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("cantrip.agent.tools.web.httpx.AsyncClient", return_value=mock_client):
            result = await tool.execute(url="https://example.com/api/data")

        assert result.success
        assert result.output == "Plain text response"
        assert "llms_txt_url" not in result.data

    @pytest.mark.asyncio
    async def test_llms_txt_probe_timeout_ignored(self, tool):
        """Probe timeout should not break the main fetch."""
        html_resp = _make_response(
            text="<html><body><p>Content</p></body></html>",
            content_type="text/html",
            url="https://example.com/",
        )

        async def mock_get(url, **_kwargs):
            url_str = str(url)
            if "llms.txt" in url_str:
                raise httpx.TimeoutException("probe timed out")
            return html_resp

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=mock_get)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("cantrip.agent.tools.web.httpx.AsyncClient", return_value=mock_client):
            result = await tool.execute(url="https://example.com/")

        assert result.success
        assert "Content" in result.output

    @pytest.mark.asyncio
    async def test_html_error_page_not_accepted_as_llms_txt(self, tool):
        """An HTML 200 at the llms.txt path should be rejected."""
        html_llms = _make_response(
            text="<html>Error page</html>",
            content_type="text/html",
            url="https://example.com/.well-known/llms.txt",
        )
        html_resp = _make_response(
            text="<html><body>Real page</body></html>",
            content_type="text/html",
            url="https://example.com/",
        )

        async def mock_get(url, **_kwargs):
            url_str = str(url)
            if "llms.txt" in url_str:
                return html_llms
            return html_resp

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=mock_get)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("cantrip.agent.tools.web.httpx.AsyncClient", return_value=mock_client):
            result = await tool.execute(url="https://example.com/")

        assert result.success
        # Should fall through to normal HTML stripping.
        assert "Real page" in result.output
        assert "llms_txt_url" not in result.data
