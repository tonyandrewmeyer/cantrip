"""Tests for the Docker Hub registry tools."""

import json
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from cantrip.agent.tools.oci_registry import (
    MAX_SEARCH_RESULTS,
    RegistryImageInfoTool,
    RegistrySearchTool,
    _format_bytes,
    _format_count,
    _normalise_image,
)


def _make_response(
    *,
    status_code: int = 200,
    json_body: dict | None = None,
    url: str = "https://hub.docker.com/v2/search/repositories/",
) -> httpx.Response:
    """Build a minimal httpx.Response for testing."""
    body = json.dumps(json_body or {}).encode()
    return httpx.Response(
        status_code=status_code,
        content=body,
        headers={"content-type": "application/json"},
        request=httpx.Request("GET", url),
    )


def _mock_client(response: httpx.Response | None = None, side_effect: Exception | None = None):
    """Create a mock httpx.AsyncClient context manager."""
    mock = AsyncMock()
    if side_effect:
        mock.get = AsyncMock(side_effect=side_effect)
    else:
        mock.get = AsyncMock(return_value=response)
    mock.__aenter__ = AsyncMock(return_value=mock)
    mock.__aexit__ = AsyncMock(return_value=False)
    return mock


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


class TestNormaliseImage:
    """Tests for _normalise_image."""

    def test_bare_name(self):
        """Bare names are expanded to library/<name>."""
        assert _normalise_image("redis") == ("library", "redis")

    def test_namespaced_name(self):
        """Namespaced names are split correctly."""
        assert _normalise_image("bitnami/redis") == ("bitnami", "redis")


class TestFormatBytes:
    """Tests for _format_bytes."""

    def test_bytes(self):
        assert _format_bytes(500) == "500 B"

    def test_kilobytes(self):
        assert _format_bytes(2_500) == "2 KB"

    def test_megabytes(self):
        assert _format_bytes(123_000_000) == "123 MB"

    def test_gigabytes(self):
        assert _format_bytes(1_200_000_000) == "1.2 GB"


class TestFormatCount:
    """Tests for _format_count."""

    def test_small_number(self):
        assert _format_count(42) == "42"

    def test_thousands(self):
        assert _format_count(456_000) == "456.0K"

    def test_millions(self):
        assert _format_count(1_200_000) == "1.2M"

    def test_billions(self):
        assert _format_count(1_200_000_000) == "1.2B"


# ---------------------------------------------------------------------------
# RegistrySearchTool
# ---------------------------------------------------------------------------


class TestRegistrySearchTool:
    """Tests for RegistrySearchTool."""

    @pytest.fixture
    def tool(self):
        return RegistrySearchTool()

    def test_tool_properties(self, tool):
        """Tool exposes the expected name, description, and parameters."""
        assert tool.name == "registry_search"
        assert "Docker Hub" in tool.description
        assert "query" in tool.parameters["properties"]
        assert "query" in tool.parameters["required"]

    @pytest.mark.asyncio
    async def test_successful_search(self, tool):
        """Successful search returns formatted results."""
        body = {
            "results": [
                {
                    "repo_name": "redis",
                    "short_description": "Redis is an open source data structure server.",
                    "star_count": 12000,
                    "pull_count": 1_200_000_000,
                    "is_official": True,
                },
                {
                    "repo_name": "bitnami/redis",
                    "short_description": "Bitnami Redis Docker Image",
                    "star_count": 250,
                    "pull_count": 50_000_000,
                    "is_official": False,
                },
            ]
        }
        resp = _make_response(json_body=body)
        mock = _mock_client(response=resp)

        with patch("cantrip.agent.tools.oci_registry.httpx.AsyncClient", return_value=mock):
            result = await tool.execute(query="redis")

        assert result.success
        assert "redis" in result.output
        assert "bitnami/redis" in result.output
        assert result.data["total"] == 2
        assert result.data["query"] == "redis"
        assert len(result.data["results"]) == 2
        assert result.data["results"][0]["repo_name"] == "redis"

    @pytest.mark.asyncio
    async def test_empty_results(self, tool):
        """Empty search returns a helpful message."""
        resp = _make_response(json_body={"results": []})
        mock = _mock_client(response=resp)

        with patch("cantrip.agent.tools.oci_registry.httpx.AsyncClient", return_value=mock):
            result = await tool.execute(query="nonexistent-image-xyz")

        assert result.success
        assert "No images found" in result.output
        assert result.data["total"] == 0

    @pytest.mark.asyncio
    async def test_result_truncation(self, tool):
        """Results exceeding MAX_SEARCH_RESULTS are truncated."""
        results = [
            {
                "repo_name": f"image-{i}",
                "short_description": f"Image number {i}",
                "star_count": 10,
                "pull_count": 1000,
                "is_official": False,
            }
            for i in range(20)
        ]
        resp = _make_response(json_body={"results": results})
        mock = _mock_client(response=resp)

        with patch("cantrip.agent.tools.oci_registry.httpx.AsyncClient", return_value=mock):
            result = await tool.execute(query="image")

        assert result.success
        assert len(result.data["results"]) == MAX_SEARCH_RESULTS
        assert result.data["total"] == 20
        assert f"showing first {MAX_SEARCH_RESULTS}" in result.output

    @pytest.mark.asyncio
    async def test_official_badge(self, tool):
        """Official images are marked with [official] in output."""
        body = {
            "results": [
                {
                    "repo_name": "nginx",
                    "short_description": "Official Nginx image",
                    "star_count": 5000,
                    "pull_count": 500_000_000,
                    "is_official": True,
                },
            ]
        }
        resp = _make_response(json_body=body)
        mock = _mock_client(response=resp)

        with patch("cantrip.agent.tools.oci_registry.httpx.AsyncClient", return_value=mock):
            result = await tool.execute(query="nginx")

        assert result.success
        assert "[official]" in result.output
        assert result.data["results"][0]["is_official"] is True

    @pytest.mark.asyncio
    async def test_timeout(self, tool):
        """Timeout produces a clear error message."""
        mock = _mock_client(side_effect=httpx.TimeoutException("timed out"))

        with patch("cantrip.agent.tools.oci_registry.httpx.AsyncClient", return_value=mock):
            result = await tool.execute(query="redis")

        assert not result.success
        assert "timed out" in result.error.lower()

    @pytest.mark.asyncio
    async def test_http_error(self, tool):
        """HTTP errors produce a failed ToolResult."""
        resp = _make_response(status_code=500)
        resp.raise_for_status = lambda: (_ for _ in ()).throw(
            httpx.HTTPStatusError("Server Error", request=resp.request, response=resp)
        )
        mock = _mock_client(response=resp)

        with patch("cantrip.agent.tools.oci_registry.httpx.AsyncClient", return_value=mock):
            result = await tool.execute(query="redis")

        assert not result.success
        assert "500" in result.error

    @pytest.mark.asyncio
    async def test_connection_error(self, tool):
        """Connection errors produce a failed ToolResult."""
        mock = _mock_client(side_effect=httpx.ConnectError("Connection refused"))

        with patch("cantrip.agent.tools.oci_registry.httpx.AsyncClient", return_value=mock):
            result = await tool.execute(query="redis")

        assert not result.success
        assert "connection error" in result.error.lower()


# ---------------------------------------------------------------------------
# RegistryImageInfoTool
# ---------------------------------------------------------------------------


class TestRegistryImageInfoTool:
    """Tests for RegistryImageInfoTool."""

    @pytest.fixture
    def tool(self):
        return RegistryImageInfoTool()

    def test_tool_properties(self, tool):
        """Tool exposes the expected name, description, and parameters."""
        assert tool.name == "registry_image_info"
        assert "Docker Hub" in tool.description
        assert "image" in tool.parameters["properties"]
        assert "image" in tool.parameters["required"]

    @pytest.mark.asyncio
    async def test_successful_info(self, tool):
        """Successful info returns formatted tag listing."""
        body = {
            "results": [
                {
                    "name": "7-alpine",
                    "full_size": 32_000_000,
                    "last_updated": "2025-01-15T10:30:00Z",
                    "images": [
                        {"architecture": "amd64"},
                        {"architecture": "arm64"},
                    ],
                },
                {
                    "name": "latest",
                    "full_size": 120_000_000,
                    "last_updated": "2025-01-14T08:00:00Z",
                    "images": [
                        {"architecture": "amd64"},
                    ],
                },
            ]
        }
        resp = _make_response(
            json_body=body,
            url="https://hub.docker.com/v2/repositories/library/redis/tags/",
        )
        mock = _mock_client(response=resp)

        with patch("cantrip.agent.tools.oci_registry.httpx.AsyncClient", return_value=mock):
            result = await tool.execute(image="redis")

        assert result.success
        assert "7-alpine" in result.output
        assert "latest" in result.output
        assert "amd64" in result.output
        assert "arm64" in result.output
        assert result.data["image"] == "redis"
        assert len(result.data["tags"]) == 2
        assert result.data["tags"][0]["name"] == "7-alpine"
        assert "amd64" in result.data["tags"][0]["architectures"]

    @pytest.mark.asyncio
    async def test_official_image_normalisation(self, tool):
        """Bare image names are normalised to library/<name>."""
        body = {"results": []}
        resp = _make_response(
            json_body=body,
            url="https://hub.docker.com/v2/repositories/library/redis/tags/",
        )
        mock = _mock_client(response=resp)

        with patch("cantrip.agent.tools.oci_registry.httpx.AsyncClient", return_value=mock):
            await tool.execute(image="redis")

        # Verify the URL includes library/redis.
        call_args = mock.get.call_args
        url = call_args.args[0] if call_args.args else call_args.kwargs.get("url", "")
        assert "library/redis" in url

    @pytest.mark.asyncio
    async def test_namespaced_image(self, tool):
        """Namespaced images are passed through without modification."""
        body = {"results": []}
        resp = _make_response(
            json_body=body,
            url="https://hub.docker.com/v2/repositories/bitnami/redis/tags/",
        )
        mock = _mock_client(response=resp)

        with patch("cantrip.agent.tools.oci_registry.httpx.AsyncClient", return_value=mock):
            await tool.execute(image="bitnami/redis")

        call_args = mock.get.call_args
        url = call_args.args[0] if call_args.args else call_args.kwargs.get("url", "")
        assert "bitnami/redis" in url

    @pytest.mark.asyncio
    async def test_specific_tag_filter(self, tool):
        """When a tag is specified, only matching tags appear in results."""
        body = {
            "results": [
                {
                    "name": "7-alpine",
                    "full_size": 32_000_000,
                    "last_updated": "2025-01-15T10:30:00Z",
                    "images": [{"architecture": "amd64"}],
                },
                {
                    "name": "latest",
                    "full_size": 120_000_000,
                    "last_updated": "2025-01-14T08:00:00Z",
                    "images": [{"architecture": "amd64"}],
                },
            ]
        }
        resp = _make_response(json_body=body)
        mock = _mock_client(response=resp)

        with patch("cantrip.agent.tools.oci_registry.httpx.AsyncClient", return_value=mock):
            result = await tool.execute(image="redis", tag="7-alpine")

        assert result.success
        assert len(result.data["tags"]) == 1
        assert result.data["tags"][0]["name"] == "7-alpine"
        assert "latest" not in result.output

    @pytest.mark.asyncio
    async def test_image_not_found(self, tool):
        """404 produces a clear 'not found' error."""
        resp = _make_response(
            status_code=404,
            url="https://hub.docker.com/v2/repositories/library/nonexistent/tags/",
        )
        resp.raise_for_status = lambda: (_ for _ in ()).throw(
            httpx.HTTPStatusError("Not Found", request=resp.request, response=resp)
        )
        mock = _mock_client(response=resp)

        with patch("cantrip.agent.tools.oci_registry.httpx.AsyncClient", return_value=mock):
            result = await tool.execute(image="nonexistent")

        assert not result.success
        assert "not found" in result.error.lower()
        assert result.data["status_code"] == 404

    @pytest.mark.asyncio
    async def test_timeout(self, tool):
        """Timeout produces a clear error message."""
        mock = _mock_client(side_effect=httpx.TimeoutException("timed out"))

        with patch("cantrip.agent.tools.oci_registry.httpx.AsyncClient", return_value=mock):
            result = await tool.execute(image="redis")

        assert not result.success
        assert "timed out" in result.error.lower()

    @pytest.mark.asyncio
    async def test_connection_error(self, tool):
        """Connection errors produce a failed ToolResult."""
        mock = _mock_client(side_effect=httpx.ConnectError("Connection refused"))

        with patch("cantrip.agent.tools.oci_registry.httpx.AsyncClient", return_value=mock):
            result = await tool.execute(image="redis")

        assert not result.success
        assert "connection error" in result.error.lower()
