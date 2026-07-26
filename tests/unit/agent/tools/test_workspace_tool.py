"""Tests for :class:`WorkspaceInfoTool` (Phase 33.3)."""

from __future__ import annotations

import textwrap
from typing import TYPE_CHECKING
from unittest import mock

import pytest

from cantrip.agent.tools.workspace import WorkspaceInfoTool

if TYPE_CHECKING:
    import pathlib


def _write(root: pathlib.Path, body: str) -> pathlib.Path:
    path = root / "cantrip.workspace.yaml"
    path.write_text(textwrap.dedent(body).lstrip())
    return path


class TestWorkspaceInfoTool:
    @pytest.fixture
    def tool(self):
        return WorkspaceInfoTool()

    @pytest.mark.asyncio
    async def test_missing_manifest_errors(self, tool, tmp_path: pathlib.Path):
        result = await tool.execute(path=str(tmp_path))
        assert not result.success
        assert "cantrip.workspace.yaml" in result.error

    @pytest.mark.asyncio
    async def test_malformed_manifest_errors(self, tool, tmp_path: pathlib.Path):
        _write(tmp_path, "workspace: demo\ncharms: []\n")
        result = await tool.execute(path=str(tmp_path))
        assert not result.success
        assert "at least one charm" in result.error

    @pytest.mark.asyncio
    async def test_reports_charms_and_relations(self, tool, tmp_path: pathlib.Path):
        _write(
            tmp_path,
            """
            workspace: demo
            charms:
              - name: api
                path: ./api-op
              - name: worker
                path: ./worker-op
            relations:
              - provider: api:workers
                requirer: worker:coordinator
                interface: worker-coordination
            shared_config:
              log_level: info
            """,
        )
        result = await tool.execute(path=str(tmp_path))
        assert result.success
        assert "Workspace: demo" in result.output
        assert "api" in result.output and "worker" in result.output
        assert "worker-coordination" in result.output
        assert "log_level: info" in result.output
        # Structured payload is present for downstream tooling / tests.
        assert result.data["workspace"] == "demo"
        assert len(result.data["charms"]) == 2
        assert len(result.data["relations"]) == 1
        assert "manifest" in result.data

    @pytest.mark.asyncio
    async def test_walks_up_from_nested_path(self, tool, tmp_path: pathlib.Path):
        """Running from inside a charm subdirectory still finds the manifest."""
        _write(
            tmp_path,
            """
            workspace: nested
            charms:
              - name: only
                path: ./only-op
            """,
        )
        (tmp_path / "only-op" / "src").mkdir(parents=True)
        result = await tool.execute(path=str(tmp_path / "only-op" / "src"))
        assert result.success
        assert "Workspace: nested" in result.output

    @pytest.mark.asyncio
    async def test_defaults_to_cwd(self, tool, tmp_path: pathlib.Path):
        """With no path argument, the tool walks upwards from cwd."""
        _write(
            tmp_path,
            """
            workspace: cwd-demo
            charms:
              - name: a
                path: ./a
            """,
        )
        with mock.patch(
            "cantrip.agent.tools.workspace.pathlib.Path.cwd",
            return_value=tmp_path,
        ):
            result = await tool.execute()
        assert result.success
        assert "Workspace: cwd-demo" in result.output
