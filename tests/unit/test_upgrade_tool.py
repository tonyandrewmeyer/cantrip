"""Tests for the upgrade testing tool."""

from cantrip.agent.tools.upgrade import UpgradeTestTool, _check_hook_failures


class TestUpgradeTestTool:
    """Tests for UpgradeTestTool basics."""

    def test_tool_name(self) -> None:
        tool = UpgradeTestTool()
        assert tool.name == "upgrade_test"

    def test_parameters_schema(self) -> None:
        tool = UpgradeTestTool()
        params = tool.parameters
        props = params["properties"]
        assert "app" in props
        assert "charm_path" in props
        assert "model" in props
        assert "resources" in props
        assert "timeout" in props

    def test_required_fields(self) -> None:
        tool = UpgradeTestTool()
        assert "app" in tool.parameters["required"]
        assert "charm_path" in tool.parameters["required"]


class TestCheckHookFailures:
    """Tests for _check_hook_failures helper."""

    def test_returns_empty_for_no_failures(self) -> None:
        """Without juju CLI, returns empty list."""
        # This calls juju which isn't available in unit tests.
        result = _check_hook_failures("nonexistent-app", "nonexistent-model")
        assert result == []
