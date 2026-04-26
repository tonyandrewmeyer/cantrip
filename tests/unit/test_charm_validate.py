"""Tests for CharmValidateTool."""

import pathlib
import tempfile
from unittest import mock

import pytest

from cantrip.agent.tools.base import ToolResult
from cantrip.agent.tools.charm import CharmValidateTool


def _test_result(
    success: bool,
    output: str = "",
    error: str | None = None,
    data: dict | None = None,
) -> ToolResult:
    """Build a ToolResult for mocking delegated tool calls."""
    return ToolResult(success=success, output=output, error=error, data=data or {})


class TestCharmValidateTool:
    """Tests for CharmValidateTool orchestration logic."""

    @pytest.fixture
    def temp_dir(self):
        """Create a temporary directory with tests/unit/ present."""
        with tempfile.TemporaryDirectory() as td:
            (pathlib.Path(td) / "tests" / "unit").mkdir(parents=True)
            yield pathlib.Path(td)

    @pytest.fixture
    def tool(self):
        return CharmValidateTool()

    @pytest.mark.asyncio
    async def test_both_steps_pass(self, tool, temp_dir):
        """Overall PASSED when tests pass and pack succeeds."""
        test_result = _test_result(
            True, output="all passed", data={"summary": {"passed": 5, "failed": 0}}
        )
        pack_result = _test_result(
            True, output="packed", data={"charm_file": str(temp_dir / "my-charm_amd64.charm")}
        )

        with (
            mock.patch(
                "cantrip.agent.tools.charm.RunCharmTestsTool.execute",
                return_value=test_result,
            ),
            mock.patch(
                "cantrip.agent.tools.charm.CharmcraftPackTool.execute",
                return_value=pack_result,
            ),
        ):
            result = await tool.execute(path=str(temp_dir))

        assert result.success
        assert result.data["overall"] == "passed"
        assert result.data["tests"]["status"] == "passed"
        assert result.data["pack"]["status"] == "passed"

    @pytest.mark.asyncio
    async def test_tests_fail_pack_still_runs(self, tool, temp_dir):
        """Overall FAILED when tests fail; pack still executes."""
        test_result = _test_result(
            False,
            error="Tests failed (exit code 1)",
            data={"summary": {"passed": 3, "failed": 2}},
        )
        pack_result = _test_result(
            True, output="packed", data={"charm_file": str(temp_dir / "my-charm_amd64.charm")}
        )

        with (
            mock.patch(
                "cantrip.agent.tools.charm.RunCharmTestsTool.execute",
                return_value=test_result,
            ) as mock_tests,
            mock.patch(
                "cantrip.agent.tools.charm.CharmcraftPackTool.execute",
                return_value=pack_result,
            ) as mock_pack,
        ):
            result = await tool.execute(path=str(temp_dir))

        assert not result.success
        assert result.data["overall"] == "failed"
        assert result.data["tests"]["status"] == "failed"
        assert result.data["pack"]["status"] == "passed"
        # Both tools were called.
        mock_tests.assert_called_once()
        mock_pack.assert_called_once()

    @pytest.mark.asyncio
    async def test_tests_pass_pack_fails(self, tool, temp_dir):
        """Overall FAILED when tests pass but pack fails."""
        test_result = _test_result(
            True, output="all passed", data={"summary": {"passed": 5, "failed": 0}}
        )
        pack_result = _test_result(False, error="charmcraft pack failed")

        with (
            mock.patch(
                "cantrip.agent.tools.charm.RunCharmTestsTool.execute",
                return_value=test_result,
            ),
            mock.patch(
                "cantrip.agent.tools.charm.CharmcraftPackTool.execute",
                return_value=pack_result,
            ),
        ):
            result = await tool.execute(path=str(temp_dir))

        assert not result.success
        assert result.data["overall"] == "failed"
        assert result.data["tests"]["status"] == "passed"
        assert result.data["pack"]["status"] == "failed"

    @pytest.mark.asyncio
    async def test_both_fail(self, tool, temp_dir):
        """Overall FAILED when both tests and pack fail."""
        test_result = _test_result(
            False,
            error="Tests failed (exit code 1)",
            data={"summary": {"passed": 0, "failed": 3}},
        )
        pack_result = _test_result(False, error="charmcraft pack failed")

        with (
            mock.patch(
                "cantrip.agent.tools.charm.RunCharmTestsTool.execute",
                return_value=test_result,
            ),
            mock.patch(
                "cantrip.agent.tools.charm.CharmcraftPackTool.execute",
                return_value=pack_result,
            ),
        ):
            result = await tool.execute(path=str(temp_dir))

        assert not result.success
        assert result.data["overall"] == "failed"
        assert result.data["tests"]["status"] == "failed"
        assert result.data["pack"]["status"] == "failed"

    @pytest.mark.asyncio
    async def test_skip_tests(self, tool, temp_dir):
        """Tests are skipped when skip_tests=True; only pack runs."""
        pack_result = _test_result(
            True, output="packed", data={"charm_file": str(temp_dir / "my-charm_amd64.charm")}
        )

        with (
            mock.patch(
                "cantrip.agent.tools.charm.RunCharmTestsTool.execute",
            ) as mock_tests,
            mock.patch(
                "cantrip.agent.tools.charm.CharmcraftPackTool.execute",
                return_value=pack_result,
            ),
        ):
            result = await tool.execute(path=str(temp_dir), skip_tests=True)

        assert result.success
        assert result.data["tests"]["status"] == "skipped"
        assert result.data["overall"] == "passed"
        mock_tests.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_test_directory(self, tool):
        """Tests are auto-skipped when tests/unit/ does not exist."""
        with tempfile.TemporaryDirectory() as td:
            pack_result = _test_result(
                True, output="packed", data={"charm_file": f"{td}/my-charm_amd64.charm"}
            )

            with (
                mock.patch(
                    "cantrip.agent.tools.charm.RunCharmTestsTool.execute",
                ) as mock_tests,
                mock.patch(
                    "cantrip.agent.tools.charm.CharmcraftPackTool.execute",
                    return_value=pack_result,
                ),
            ):
                result = await tool.execute(path=td)

        assert result.success
        assert result.data["tests"]["status"] == "skipped"
        assert result.data["overall"] == "passed"
        mock_tests.assert_not_called()

    @pytest.mark.asyncio
    async def test_path_not_found(self, tool):
        """Error when path does not exist."""
        result = await tool.execute(path="/nonexistent/path/to/charm")

        assert not result.success
        assert "not found" in result.error.lower()

    @pytest.mark.asyncio
    async def test_report_format(self, tool, temp_dir):
        """Output contains expected report sections."""
        test_result = _test_result(
            True, output="all passed", data={"summary": {"passed": 3, "failed": 0}}
        )
        pack_result = _test_result(
            True, output="packed", data={"charm_file": str(temp_dir / "my-charm_amd64.charm")}
        )

        with (
            mock.patch(
                "cantrip.agent.tools.charm.RunCharmTestsTool.execute",
                return_value=test_result,
            ),
            mock.patch(
                "cantrip.agent.tools.charm.CharmcraftPackTool.execute",
                return_value=pack_result,
            ),
        ):
            result = await tool.execute(path=str(temp_dir))

        assert "Validation Report" in result.output
        assert "Unit tests:" in result.output
        assert "Charmcraft pack:" in result.output
        assert "Overall:" in result.output

    @pytest.mark.asyncio
    async def test_charm_file_in_data(self, tool, temp_dir):
        """.charm file path is present in data when pack succeeds."""
        charm_file = str(temp_dir / "my-charm_amd64.charm")
        test_result = _test_result(
            True, output="all passed", data={"summary": {"passed": 1, "failed": 0}}
        )
        pack_result = _test_result(True, output="packed", data={"charm_file": charm_file})

        with (
            mock.patch(
                "cantrip.agent.tools.charm.RunCharmTestsTool.execute",
                return_value=test_result,
            ),
            mock.patch(
                "cantrip.agent.tools.charm.CharmcraftPackTool.execute",
                return_value=pack_result,
            ),
        ):
            result = await tool.execute(path=str(temp_dir))

        assert result.data["pack"]["charm_file"] == charm_file
