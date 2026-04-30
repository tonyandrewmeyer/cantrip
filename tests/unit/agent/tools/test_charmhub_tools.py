"""Tests for the Charmhub API tools."""

import json
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from cantrip.agent.tools.charmhub import (
    MAX_SEARCH_RESULTS,
    CharmhubInfoTool,
    CharmhubSearchTool,
)


def _make_response(
    *,
    status_code: int = 200,
    json_body: dict | None = None,
    url: str = "https://api.charmhub.io/v2/charms/find",
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
# CharmhubSearchTool
# ---------------------------------------------------------------------------


class TestCharmhubSearchTool:
    """Tests for CharmhubSearchTool."""

    @pytest.fixture
    def tool(self):
        return CharmhubSearchTool()

    def test_tool_properties(self, tool):
        """Tool exposes the expected name, description, and parameters."""
        assert tool.name == "charmhub_search"
        assert "Charmhub" in tool.description
        assert "query" in tool.parameters["properties"]
        assert "query" in tool.parameters["required"]

    @pytest.mark.asyncio
    async def test_successful_search(self, tool):
        """Successful search returns formatted results."""
        body = {
            "results": [
                {
                    "name": "postgresql-k8s",
                    "result": {
                        "summary": "PostgreSQL on Kubernetes",
                        "publisher": {"display-name": "Canonical"},
                        "categories": [{"name": "databases"}],
                    },
                },
                {
                    "name": "postgresql",
                    "result": {
                        "summary": "PostgreSQL on machines",
                        "publisher": {"display-name": "Canonical"},
                        "categories": [{"name": "databases"}],
                    },
                },
            ]
        }
        resp = _make_response(json_body=body)
        mock = _mock_client(response=resp)

        with patch("cantrip.agent.tools.charmhub.httpx.AsyncClient", return_value=mock):
            result = await tool.execute(query="postgresql")

        assert result.success
        assert "postgresql-k8s" in result.output
        assert "postgresql" in result.output
        assert result.data["total"] == 2
        assert result.data["query"] == "postgresql"
        assert len(result.data["results"]) == 2
        assert result.data["results"][0]["name"] == "postgresql-k8s"

    @pytest.mark.asyncio
    async def test_empty_results(self, tool):
        """Empty search returns a helpful message."""
        resp = _make_response(json_body={"results": []})
        mock = _mock_client(response=resp)

        with patch("cantrip.agent.tools.charmhub.httpx.AsyncClient", return_value=mock):
            result = await tool.execute(query="nonexistent-charm-xyz")

        assert result.success
        assert "No charms found" in result.output
        assert result.data["total"] == 0

    @pytest.mark.asyncio
    async def test_category_filter(self, tool):
        """Category parameter is passed through to the API."""
        resp = _make_response(json_body={"results": []})
        mock = _mock_client(response=resp)

        with patch("cantrip.agent.tools.charmhub.httpx.AsyncClient", return_value=mock):
            await tool.execute(query="redis", category="databases")

        call_kwargs = mock.get.call_args
        assert "category" in call_kwargs.kwargs.get(
            "params", call_kwargs.args[1] if len(call_kwargs.args) > 1 else {}
        ) or "category" in str(call_kwargs)

    @pytest.mark.asyncio
    async def test_result_truncation(self, tool):
        """Results exceeding MAX_SEARCH_RESULTS are truncated."""
        results = [
            {
                "name": f"charm-{i}",
                "result": {
                    "summary": f"Charm number {i}",
                    "publisher": {"display-name": "Test"},
                    "categories": [],
                },
            }
            for i in range(30)
        ]
        resp = _make_response(json_body={"results": results})
        mock = _mock_client(response=resp)

        with patch("cantrip.agent.tools.charmhub.httpx.AsyncClient", return_value=mock):
            result = await tool.execute(query="charm")

        assert result.success
        assert len(result.data["results"]) == MAX_SEARCH_RESULTS
        assert result.data["total"] == 30
        assert f"showing first {MAX_SEARCH_RESULTS}" in result.output

    @pytest.mark.asyncio
    async def test_timeout(self, tool):
        """Timeout produces a clear error message."""
        mock = _mock_client(side_effect=httpx.TimeoutException("timed out"))

        with patch("cantrip.agent.tools.charmhub.httpx.AsyncClient", return_value=mock):
            result = await tool.execute(query="postgresql")

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

        with patch("cantrip.agent.tools.charmhub.httpx.AsyncClient", return_value=mock):
            result = await tool.execute(query="postgresql")

        assert not result.success
        assert "500" in result.error

    @pytest.mark.asyncio
    async def test_connection_error(self, tool):
        """Connection errors produce a failed ToolResult."""
        mock = _mock_client(side_effect=httpx.ConnectError("Connection refused"))

        with patch("cantrip.agent.tools.charmhub.httpx.AsyncClient", return_value=mock):
            result = await tool.execute(query="postgresql")

        assert not result.success
        assert "connection error" in result.error.lower()

    @pytest.mark.asyncio
    async def test_http_404_error(self, tool):
        """HTTP 404 produces a failed ToolResult."""
        resp = _make_response(status_code=404)
        resp.raise_for_status = lambda: (_ for _ in ()).throw(
            httpx.HTTPStatusError("Not Found", request=resp.request, response=resp)
        )
        mock = _mock_client(response=resp)

        with patch("cantrip.agent.tools.charmhub.httpx.AsyncClient", return_value=mock):
            result = await tool.execute(query="postgresql")

        assert not result.success
        assert "404" in result.error


# ---------------------------------------------------------------------------
# CharmhubInfoTool
# ---------------------------------------------------------------------------


class TestCharmhubInfoTool:
    """Tests for CharmhubInfoTool."""

    @pytest.fixture
    def tool(self):
        return CharmhubInfoTool()

    def test_tool_properties(self, tool):
        """Tool exposes the expected name, description, and parameters."""
        assert tool.name == "charmhub_info"
        assert "Charmhub" in tool.description
        assert "name" in tool.parameters["properties"]
        assert "name" in tool.parameters["required"]

    @pytest.mark.asyncio
    async def test_successful_info(self, tool):
        """Successful info returns formatted metadata and config."""
        metadata_yaml = """
name: postgresql-k8s
summary: PostgreSQL on Kubernetes
description: A full-featured PostgreSQL charm for Kubernetes.
provides:
  database:
    interface: postgresql_client
requires:
  tracing:
    interface: tracing
peers:
  replication:
    interface: postgresql_peers
storage:
  pgdata:
    type: filesystem
containers:
  postgresql:
    resource: oci-image
"""
        config_yaml = """
options:
  max-connections:
    type: int
    description: Maximum number of database connections.
    default: 100
  log-level:
    type: string
    description: Logging verbosity.
    default: info
"""
        body = {
            "default-release": {
                "revision": {
                    "metadata-yaml": metadata_yaml,
                    "config-yaml": config_yaml,
                },
            },
        }
        resp = _make_response(
            json_body=body,
            url="https://api.charmhub.io/v2/charms/info/postgresql-k8s",
        )
        mock = _mock_client(response=resp)

        with patch("cantrip.agent.tools.charmhub.httpx.AsyncClient", return_value=mock):
            result = await tool.execute(name="postgresql-k8s")

        assert result.success
        assert "postgresql-k8s" in result.output
        assert "postgresql_client" in result.output
        assert "tracing" in result.output
        assert "replication" in result.output
        assert "pgdata" in result.output
        assert "max-connections" in result.output
        assert result.data["name"] == "postgresql-k8s"
        assert result.data["metadata"]["name"] == "postgresql-k8s"
        assert "options" in result.data["config"]

    @pytest.mark.asyncio
    async def test_relations_in_data(self, tool):
        """Relations are correctly extracted into metadata."""
        metadata_yaml = """
name: redis-k8s
provides:
  redis:
    interface: redis
requires:
  certificates:
    interface: tls-certificates
"""
        body = {
            "default-release": {
                "revision": {
                    "metadata-yaml": metadata_yaml,
                },
            },
        }
        resp = _make_response(
            json_body=body,
            url="https://api.charmhub.io/v2/charms/info/redis-k8s",
        )
        mock = _mock_client(response=resp)

        with patch("cantrip.agent.tools.charmhub.httpx.AsyncClient", return_value=mock):
            result = await tool.execute(name="redis-k8s")

        assert result.success
        metadata = result.data["metadata"]
        assert "redis" in metadata["provides"]
        assert metadata["provides"]["redis"]["interface"] == "redis"
        assert "certificates" in metadata["requires"]

    @pytest.mark.asyncio
    async def test_config_in_data(self, tool):
        """Config options are correctly parsed into data."""
        config_yaml = """
options:
  port:
    type: int
    default: 6379
"""
        body = {
            "default-release": {
                "revision": {
                    "metadata-yaml": "name: redis-k8s\nsummary: Redis",
                    "config-yaml": config_yaml,
                },
            },
        }
        resp = _make_response(
            json_body=body,
            url="https://api.charmhub.io/v2/charms/info/redis-k8s",
        )
        mock = _mock_client(response=resp)

        with patch("cantrip.agent.tools.charmhub.httpx.AsyncClient", return_value=mock):
            result = await tool.execute(name="redis-k8s")

        assert result.success
        assert result.data["config"]["options"]["port"]["type"] == "int"

    @pytest.mark.asyncio
    async def test_missing_metadata_yaml(self, tool):
        """Gracefully handles missing metadata-yaml."""
        body = {
            "default-release": {
                "revision": {},
            },
        }
        resp = _make_response(
            json_body=body,
            url="https://api.charmhub.io/v2/charms/info/some-charm",
        )
        mock = _mock_client(response=resp)

        with patch("cantrip.agent.tools.charmhub.httpx.AsyncClient", return_value=mock):
            result = await tool.execute(name="some-charm")

        assert result.success
        assert result.data["metadata"] == {}
        assert result.data["config"] == {}

    @pytest.mark.asyncio
    async def test_malformed_yaml(self, tool):
        """Malformed YAML is handled gracefully."""
        body = {
            "default-release": {
                "revision": {
                    "metadata-yaml": "{{invalid yaml: [",
                    "config-yaml": "also: {{broken",
                },
            },
        }
        resp = _make_response(
            json_body=body,
            url="https://api.charmhub.io/v2/charms/info/bad-charm",
        )
        mock = _mock_client(response=resp)

        with patch("cantrip.agent.tools.charmhub.httpx.AsyncClient", return_value=mock):
            result = await tool.execute(name="bad-charm")

        assert result.success
        assert result.data["metadata"] == {}
        assert result.data["config"] == {}

    @pytest.mark.asyncio
    async def test_charm_not_found(self, tool):
        """404 produces a clear 'not found' error."""
        resp = _make_response(
            status_code=404,
            url="https://api.charmhub.io/v2/charms/info/nonexistent",
        )
        resp.raise_for_status = lambda: (_ for _ in ()).throw(
            httpx.HTTPStatusError("Not Found", request=resp.request, response=resp)
        )
        mock = _mock_client(response=resp)

        with patch("cantrip.agent.tools.charmhub.httpx.AsyncClient", return_value=mock):
            result = await tool.execute(name="nonexistent")

        assert not result.success
        assert "not found" in result.error.lower()
        assert result.data["status_code"] == 404

    @pytest.mark.asyncio
    async def test_timeout(self, tool):
        """Timeout produces a clear error message."""
        mock = _mock_client(side_effect=httpx.TimeoutException("timed out"))

        with patch("cantrip.agent.tools.charmhub.httpx.AsyncClient", return_value=mock):
            result = await tool.execute(name="postgresql-k8s")

        assert not result.success
        assert "timed out" in result.error.lower()

    @pytest.mark.asyncio
    async def test_connection_error(self, tool):
        """Connection errors produce a failed ToolResult."""
        mock = _mock_client(side_effect=httpx.ConnectError("Connection refused"))

        with patch("cantrip.agent.tools.charmhub.httpx.AsyncClient", return_value=mock):
            result = await tool.execute(name="postgresql-k8s")

        assert not result.success
        assert "connection error" in result.error.lower()
