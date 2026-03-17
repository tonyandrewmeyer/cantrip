"""Tests for the scaling test tool."""

from cantrip.agent.tools.scaling import ScalingTestTool


class TestScalingTestTool:
    """Tests for ScalingTestTool basics."""

    def test_tool_name(self) -> None:
        tool = ScalingTestTool()
        assert tool.name == "scaling_test"

    def test_parameters_schema(self) -> None:
        tool = ScalingTestTool()
        params = tool.parameters
        props = params["properties"]
        assert "app" in props
        assert "target_units" in props
        assert "scale_back" in props
        assert "model" in props
