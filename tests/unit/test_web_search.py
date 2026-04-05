"""Tests for the WebSearchTool and DuckDuckGo HTML parsing."""

from unittest.mock import AsyncMock, patch

import httpx
import pytest

from cantrip.agent.tools.web_search import (
    WebSearchTool,
    _fallback_parse,
    parse_ddg_lite_results,
)

# ---------------------------------------------------------------------------
# Sample HTML — modelled after DuckDuckGo lite's actual output structure
# ---------------------------------------------------------------------------

SAMPLE_DDG_HTML = """\
<html>
<body>
<table>
  <tr>
    <td>
      <a class="result-link" href="https://example.com/backup">Backup Guide</a>
    </td>
  </tr>
  <tr>
    <td class="result-snippet">
      How to back up and restore your database safely.
    </td>
  </tr>
  <tr>
    <td>
      <a class="result-link" href="https://example.com/ha">HA Setup</a>
    </td>
  </tr>
  <tr>
    <td class="result-snippet">
      Configure high availability with replication.
    </td>
  </tr>
  <tr>
    <td>
      <a class="result-link" href="https://example.com/scaling">Scaling Docs</a>
    </td>
  </tr>
  <tr>
    <td class="result-snippet">
      Horizontal and vertical scaling strategies.
    </td>
  </tr>
</table>
</body>
</html>
"""

EMPTY_HTML = "<html><body><p>No results found.</p></body></html>"

# HTML with no structured classes — for fallback parser testing.
UNSTRUCTURED_HTML = """\
<html><body>
<a href="https://duckduckgo.com/settings">Settings</a>
<a href="https://example.org/docs">Example Docs</a>
<a href="https://example.org/faq">FAQ Page</a>
</body></html>
"""


# ===================================================================
# TestParseDDGLiteResults
# ===================================================================


class TestParseDDGLiteResults:
    """Tests for parse_ddg_lite_results — DuckDuckGo lite HTML parsing."""

    def test_extracts_results(self) -> None:
        results = parse_ddg_lite_results(SAMPLE_DDG_HTML)
        assert len(results) == 3
        assert results[0].title == "Backup Guide"
        assert results[0].url == "https://example.com/backup"
        assert "back up" in results[0].snippet

    def test_respects_max_results(self) -> None:
        results = parse_ddg_lite_results(SAMPLE_DDG_HTML, max_results=2)
        assert len(results) == 2

    def test_empty_html_returns_empty(self) -> None:
        results = parse_ddg_lite_results(EMPTY_HTML)
        assert results == []

    def test_deduplicates_by_url(self) -> None:
        # Duplicate the first result in the HTML.
        doubled = SAMPLE_DDG_HTML + SAMPLE_DDG_HTML
        results = parse_ddg_lite_results(doubled, max_results=10)
        urls = [r.url for r in results]
        assert len(urls) == len(set(urls))

    def test_snippet_extracted(self) -> None:
        results = parse_ddg_lite_results(SAMPLE_DDG_HTML)
        assert results[1].snippet == "Configure high availability with replication."


# ===================================================================
# TestFallbackParse
# ===================================================================


class TestFallbackParse:
    """Tests for _fallback_parse — regex-based fallback."""

    def test_extracts_external_links(self) -> None:
        results = _fallback_parse(UNSTRUCTURED_HTML)
        urls = [r.url for r in results]
        # Should skip the duckduckgo.com link.
        assert "https://duckduckgo.com/settings" not in urls
        assert "https://example.org/docs" in urls

    def test_respects_max_results(self) -> None:
        results = _fallback_parse(UNSTRUCTURED_HTML, max_results=1)
        assert len(results) == 1

    def test_empty_html(self) -> None:
        results = _fallback_parse("<html></html>")
        assert results == []


# ===================================================================
# TestWebSearchToolExecute
# ===================================================================


class TestWebSearchToolExecute:
    """Tests for WebSearchTool.execute()."""

    @pytest.mark.asyncio
    async def test_successful_search(self) -> None:
        tool = WebSearchTool()
        mock_response = httpx.Response(
            200,
            text=SAMPLE_DDG_HTML,
            request=httpx.Request("POST", "https://lite.duckduckgo.com/lite/"),
        )
        with patch("cantrip.agent.tools.web_search.httpx.AsyncClient") as mock_client:
            instance = AsyncMock()
            instance.post.return_value = mock_response
            instance.__aenter__ = AsyncMock(return_value=instance)
            instance.__aexit__ = AsyncMock(return_value=False)
            mock_client.return_value = instance

            result = await tool.execute(query="redis backup")

        assert result.success
        assert "Backup Guide" in result.output
        assert result.data["result_count"] == 3

    @pytest.mark.asyncio
    async def test_empty_query_rejected(self) -> None:
        tool = WebSearchTool()
        result = await tool.execute(query="")
        assert not result.success
        assert "empty" in result.error.lower()

    @pytest.mark.asyncio
    async def test_whitespace_query_rejected(self) -> None:
        tool = WebSearchTool()
        result = await tool.execute(query="   ")
        assert not result.success

    @pytest.mark.asyncio
    async def test_timeout_handled(self) -> None:
        tool = WebSearchTool()
        with patch("cantrip.agent.tools.web_search.httpx.AsyncClient") as mock_client:
            instance = AsyncMock()
            instance.post.side_effect = httpx.TimeoutException("timed out")
            instance.__aenter__ = AsyncMock(return_value=instance)
            instance.__aexit__ = AsyncMock(return_value=False)
            mock_client.return_value = instance

            result = await tool.execute(query="test")

        assert not result.success
        assert "timed out" in result.error.lower()

    @pytest.mark.asyncio
    async def test_http_error_handled(self) -> None:
        tool = WebSearchTool()
        mock_response = httpx.Response(
            429,
            request=httpx.Request("POST", "https://lite.duckduckgo.com/lite/"),
        )
        with patch("cantrip.agent.tools.web_search.httpx.AsyncClient") as mock_client:
            instance = AsyncMock()
            instance.post.return_value = mock_response
            instance.__aenter__ = AsyncMock(return_value=instance)
            instance.__aexit__ = AsyncMock(return_value=False)
            mock_client.return_value = instance

            result = await tool.execute(query="test")

        assert not result.success
        assert "429" in result.error

    @pytest.mark.asyncio
    async def test_no_results_returns_success(self) -> None:
        tool = WebSearchTool()
        mock_response = httpx.Response(
            200,
            text=EMPTY_HTML,
            request=httpx.Request("POST", "https://lite.duckduckgo.com/lite/"),
        )
        with patch("cantrip.agent.tools.web_search.httpx.AsyncClient") as mock_client:
            instance = AsyncMock()
            instance.post.return_value = mock_response
            instance.__aenter__ = AsyncMock(return_value=instance)
            instance.__aexit__ = AsyncMock(return_value=False)
            mock_client.return_value = instance

            result = await tool.execute(query="xyznonexistent")

        assert result.success
        assert "No results" in result.output
        assert result.data["result_count"] == 0

    @pytest.mark.asyncio
    async def test_max_results_capped(self) -> None:
        tool = WebSearchTool()
        mock_response = httpx.Response(
            200,
            text=SAMPLE_DDG_HTML,
            request=httpx.Request("POST", "https://lite.duckduckgo.com/lite/"),
        )
        with patch("cantrip.agent.tools.web_search.httpx.AsyncClient") as mock_client:
            instance = AsyncMock()
            instance.post.return_value = mock_response
            instance.__aenter__ = AsyncMock(return_value=instance)
            instance.__aexit__ = AsyncMock(return_value=False)
            mock_client.return_value = instance

            result = await tool.execute(query="test", max_results=1)

        assert result.success
        assert result.data["result_count"] == 1

    @pytest.mark.asyncio
    async def test_connection_error_handled(self) -> None:
        tool = WebSearchTool()
        with patch("cantrip.agent.tools.web_search.httpx.AsyncClient") as mock_client:
            instance = AsyncMock()
            instance.post.side_effect = httpx.ConnectError("connection refused")
            instance.__aenter__ = AsyncMock(return_value=instance)
            instance.__aexit__ = AsyncMock(return_value=False)
            mock_client.return_value = instance

            result = await tool.execute(query="test")

        assert not result.success
        assert "Connection error" in result.error


# ===================================================================
# TestWebSearchToolSchema
# ===================================================================


class TestWebSearchToolSchema:
    """Tests for WebSearchTool metadata."""

    def test_name(self) -> None:
        assert WebSearchTool().name == "web_search"

    def test_required_parameters(self) -> None:
        params = WebSearchTool().parameters
        assert "query" in params["properties"]
        assert params["required"] == ["query"]

    def test_has_max_results_parameter(self) -> None:
        params = WebSearchTool().parameters
        assert "max_results" in params["properties"]
