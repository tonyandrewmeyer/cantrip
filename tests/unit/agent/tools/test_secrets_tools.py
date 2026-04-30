"""Tests for Juju secrets inspection tools."""

import datetime
from unittest import mock

import pytest

from cantrip.agent.tools.juju import JujuListSecretsTool, JujuShowSecretTool


@pytest.fixture()
def list_tool() -> JujuListSecretsTool:
    return JujuListSecretsTool()


@pytest.fixture()
def show_tool() -> JujuShowSecretTool:
    return JujuShowSecretTool()


def _make_secret(
    name: str = "db-creds",
    owner: str = "postgresql/0",
    uri: str = "secret:abc123",
    revision: int = 1,
    rotation: str | None = None,
    description: str | None = None,
    access: list | None = None,
) -> mock.MagicMock:
    secret = mock.MagicMock()
    secret.name = name
    secret.owner = owner
    secret.uri = uri
    secret.revision = revision
    secret.rotation = rotation
    secret.description = description
    secret.access = access or []
    secret.created = datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)
    secret.updated = datetime.datetime(2026, 1, 2, tzinfo=datetime.UTC)
    secret.expires = None
    return secret


# ===================================================================
# TestJujuListSecretsTool
# ===================================================================


class TestJujuListSecretsTool:
    """Tests for JujuListSecretsTool."""

    def test_tool_properties(self, list_tool: JujuListSecretsTool) -> None:
        assert list_tool.name == "juju_list_secrets"
        assert "secret" in list_tool.description.lower()
        assert list_tool.parameters["type"] == "object"

    @pytest.mark.asyncio()
    async def test_no_juju(self, list_tool: JujuListSecretsTool) -> None:
        with mock.patch("cantrip.agent.tools.juju._juju_available", return_value=False):
            result = await list_tool.execute()
        assert result.success is False
        assert "not found" in result.error.lower()

    @pytest.mark.asyncio()
    async def test_no_secrets(self, list_tool: JujuListSecretsTool) -> None:
        with (
            mock.patch("cantrip.agent.tools.juju._juju_available", return_value=True),
            mock.patch("cantrip.agent.tools.juju._run_juju", return_value=[]),
        ):
            result = await list_tool.execute()
        assert result.success is True
        assert result.data["count"] == 0
        assert "No secrets" in result.output

    @pytest.mark.asyncio()
    async def test_lists_secrets(self, list_tool: JujuListSecretsTool) -> None:
        secrets = [
            _make_secret(name="db-creds", owner="postgresql/0"),
            _make_secret(name="api-key", owner="myapp/0", rotation="hourly"),
        ]
        with (
            mock.patch("cantrip.agent.tools.juju._juju_available", return_value=True),
            mock.patch("cantrip.agent.tools.juju._run_juju", return_value=secrets),
        ):
            result = await list_tool.execute()

        assert result.success is True
        assert result.data["count"] == 2
        assert len(result.data["secrets"]) == 2
        assert result.data["secrets"][0]["name"] == "db-creds"
        assert result.data["secrets"][1]["rotation"] == "hourly"
        assert "db-creds" in result.output
        assert "api-key" in result.output

    @pytest.mark.asyncio()
    async def test_passes_owner_filter(self, list_tool: JujuListSecretsTool) -> None:
        with (
            mock.patch("cantrip.agent.tools.juju._juju_available", return_value=True),
            mock.patch("cantrip.agent.tools.juju._run_juju", return_value=[]) as mock_run,
        ):
            await list_tool.execute(owner="postgresql")
        mock_run.assert_called_once()
        call_kwargs = mock_run.call_args
        assert call_kwargs.kwargs.get("owner") == "postgresql"

    @pytest.mark.asyncio()
    async def test_timeout(self, list_tool: JujuListSecretsTool) -> None:
        with (
            mock.patch("cantrip.agent.tools.juju._juju_available", return_value=True),
            mock.patch("cantrip.agent.tools.juju._run_juju", side_effect=TimeoutError),
        ):
            result = await list_tool.execute()
        assert result.success is False
        assert "timed out" in result.error

    @pytest.mark.asyncio()
    async def test_secret_with_access(self, list_tool: JujuListSecretsTool) -> None:
        access_entry = mock.MagicMock()
        access_entry.scope = "myapp"
        access_entry.role = "consumer"
        secrets = [_make_secret(access=[access_entry])]
        with (
            mock.patch("cantrip.agent.tools.juju._juju_available", return_value=True),
            mock.patch("cantrip.agent.tools.juju._run_juju", return_value=secrets),
        ):
            result = await list_tool.execute()
        assert "myapp:consumer" in result.output


# ===================================================================
# TestJujuShowSecretTool
# ===================================================================


class TestJujuShowSecretTool:
    """Tests for JujuShowSecretTool."""

    def test_tool_properties(self, show_tool: JujuShowSecretTool) -> None:
        assert show_tool.name == "juju_show_secret"
        assert "identifier" in show_tool.parameters["properties"]
        assert "identifier" in show_tool.parameters["required"]

    @pytest.mark.asyncio()
    async def test_no_juju(self, show_tool: JujuShowSecretTool) -> None:
        with mock.patch("cantrip.agent.tools.juju._juju_available", return_value=False):
            result = await show_tool.execute(identifier="db-creds")
        assert result.success is False

    @pytest.mark.asyncio()
    async def test_shows_secret_metadata(self, show_tool: JujuShowSecretTool) -> None:
        secret = _make_secret(name="db-creds", description="Database credentials")
        with (
            mock.patch("cantrip.agent.tools.juju._juju_available", return_value=True),
            mock.patch("cantrip.agent.tools.juju._run_juju", return_value=secret),
        ):
            result = await show_tool.execute(identifier="db-creds")

        assert result.success is True
        assert result.data["name"] == "db-creds"
        assert result.data["owner"] == "postgresql/0"
        assert "db-creds" in result.output
        assert "Description: Database credentials" in result.output

    @pytest.mark.asyncio()
    async def test_never_reveals_content(self, show_tool: JujuShowSecretTool) -> None:
        """Secret contents are never exposed, even if the secret has content."""
        secret = _make_secret()
        secret.content = {"password": "s3cret", "username": "admin"}
        with (
            mock.patch("cantrip.agent.tools.juju._juju_available", return_value=True),
            mock.patch("cantrip.agent.tools.juju._run_juju", return_value=secret) as run_mock,
        ):
            result = await show_tool.execute(identifier="db-creds")

        assert result.success is True
        # Content must never appear in output or data.
        assert "content" not in result.data
        assert "s3cret" not in result.output
        # Reveal must always be False in the underlying call.
        _call_kwargs = run_mock.call_args
        assert _call_kwargs.kwargs.get("reveal") is False

    @pytest.mark.asyncio()
    async def test_timeout(self, show_tool: JujuShowSecretTool) -> None:
        with (
            mock.patch("cantrip.agent.tools.juju._juju_available", return_value=True),
            mock.patch("cantrip.agent.tools.juju._run_juju", side_effect=TimeoutError),
        ):
            result = await show_tool.execute(identifier="db-creds")
        assert result.success is False
        assert "timed out" in result.error

    @pytest.mark.asyncio()
    async def test_shows_access(self, show_tool: JujuShowSecretTool) -> None:
        access_entry = mock.MagicMock()
        access_entry.scope = "myapp"
        access_entry.role = "consumer"
        secret = _make_secret(access=[access_entry])
        with (
            mock.patch("cantrip.agent.tools.juju._juju_available", return_value=True),
            mock.patch("cantrip.agent.tools.juju._run_juju", return_value=secret),
        ):
            result = await show_tool.execute(identifier="db-creds")
        assert "myapp: consumer" in result.output
