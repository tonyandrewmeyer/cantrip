"""Tests for the Terraform generation and validation tools."""

import pathlib
from unittest import mock

import pytest

from cantrip.agent.tools.charm import GenerateTerraformTool, ValidateTerraformTool

_MINIMAL_CHARMCRAFT = """\
name: my-app
type: charm
bases:
  - build-on:
      - name: ubuntu
        channel: "22.04"
    run-on:
      - name: ubuntu
        channel: "22.04"
provides:
  grafana-dashboard:
    interface: grafana_dashboard
requires:
  database:
    interface: postgresql_client
"""


class TestGenerateTerraformTool:
    """Tests for GenerateTerraformTool."""

    @pytest.fixture
    def tool(self):
        return GenerateTerraformTool()

    @pytest.mark.asyncio
    async def test_generate_terraform_creates_files(self, tmp_path: pathlib.Path, tool):
        """Verify that all four Terraform files are written."""
        charmcraft = tmp_path / "charmcraft.yaml"
        charmcraft.write_text(_MINIMAL_CHARMCRAFT)

        result = await tool.execute(charm_path=str(tmp_path))

        assert result.success
        tf_dir = tmp_path / "terraform"
        assert tf_dir.is_dir()
        for filename in ("main.tf", "variables.tf", "outputs.tf", "terraform.tf"):
            assert (tf_dir / filename).exists(), f"{filename} was not created"
        assert result.data["files"] == [
            "main.tf",
            "outputs.tf",
            "terraform.tf",
            "variables.tf",
        ]

    @pytest.mark.asyncio
    async def test_generate_terraform_missing_charmcraft(self, tmp_path: pathlib.Path, tool):
        """Missing charmcraft.yaml should return an error."""
        result = await tool.execute(charm_path=str(tmp_path))

        assert not result.success
        assert "charmcraft.yaml not found" in result.error

    @pytest.mark.asyncio
    async def test_tool_name(self, tool):
        """Verify the tool name matches expectations."""
        assert tool.name == "generate_terraform"


class TestValidateTerraformTool:
    """Tests for ValidateTerraformTool."""

    @pytest.fixture
    def tool(self):
        return ValidateTerraformTool()

    @pytest.mark.asyncio
    async def test_validate_terraform_no_cli(self, tool):
        """When terraform is not installed, validation is skipped gracefully."""
        with mock.patch("shutil.which", return_value=None):
            result = await tool.execute(terraform_path="/nonexistent")

        assert result.success
        assert "not installed" in result.output
        assert result.data.get("skipped") is True

    @pytest.mark.asyncio
    async def test_tool_name(self, tool):
        """Verify the tool name matches expectations."""
        assert tool.name == "validate_terraform"


class TestToolAllowlists:
    """Verify that the new tools appear in the correct subagent allowlists."""

    def test_tools_in_build_allowlist(self):
        """Both Terraform tools should be in the BUILD category allowlist."""
        from cantrip.agent.queue import TaskCategory
        from cantrip.agent.subagent import _CATEGORY_TOOLS

        build_tools = _CATEGORY_TOOLS[TaskCategory.BUILD]
        assert "generate_terraform" in build_tools
        assert "validate_terraform" in build_tools

    def test_validate_in_test_allowlist(self):
        """validate_terraform should also be in the TEST category allowlist."""
        from cantrip.agent.queue import TaskCategory
        from cantrip.agent.subagent import _CATEGORY_TOOLS

        test_tools = _CATEGORY_TOOLS[TaskCategory.TEST]
        assert "validate_terraform" in test_tools
