"""Tests for the chaos testing tool."""

from cantrip.agent.tools.chaos import _DISRUPTIONS, ChaosTestTool


class TestChaosTestTool:
    """Tests for ChaosTestTool basics."""

    def test_tool_name(self) -> None:
        tool = ChaosTestTool()
        assert tool.name == "chaos_test"

    def test_supported_disruptions(self) -> None:
        assert "kill-unit" in _DISRUPTIONS
        assert "remove-relation" in _DISRUPTIONS
        assert "scale-down" in _DISRUPTIONS
        assert "config-reset" in _DISRUPTIONS

    def test_parameters_schema(self) -> None:
        tool = ChaosTestTool()
        params = tool.parameters
        props = params["properties"]
        assert "app" in props
        assert "disruption" in props
        assert "model" in props
        assert "relation" in props
