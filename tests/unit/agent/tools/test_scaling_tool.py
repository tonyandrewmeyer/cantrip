"""Tests for the scaling test tool."""

from types import SimpleNamespace
from unittest import mock

import pytest

from cantrip.agent.tools.scaling import ScalingTestTool, _get_unit_count


def _fake_proc(returncode: int = 0, stdout: str = "", stderr: str = "") -> SimpleNamespace:
    """Build a stand-in for ``subprocess.CompletedProcess``."""
    return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)


class TestScalingTestTool:
    """Basic metadata surface."""

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
        assert params["required"] == ["app"]

    def test_description_mentions_scaling(self) -> None:
        assert "scaling" in ScalingTestTool().description.lower()


class TestScalingTestToolExecuteGuards:
    """Early validation paths."""

    @pytest.fixture
    def tool(self) -> ScalingTestTool:
        return ScalingTestTool()

    @pytest.mark.asyncio
    async def test_juju_not_installed(self, tool: ScalingTestTool) -> None:
        with mock.patch("cantrip.agent.tools.scaling.shutil.which", return_value=None):
            result = await tool.execute(app="my-app")
        assert not result.success
        assert "juju cli not found" in result.error.lower()

    @pytest.mark.asyncio
    async def test_missing_app(self, tool: ScalingTestTool) -> None:
        with mock.patch("cantrip.agent.tools.scaling.shutil.which", return_value="/usr/bin/juju"):
            result = await tool.execute(app="")
        assert not result.success
        assert "app parameter" in result.error.lower()

    @pytest.mark.asyncio
    async def test_target_units_below_one(self, tool: ScalingTestTool) -> None:
        with mock.patch("cantrip.agent.tools.scaling.shutil.which", return_value="/usr/bin/juju"):
            result = await tool.execute(app="my-app", target_units=0)
        assert not result.success
        assert "target_units must be at least 1" in result.error


class TestScalingTestToolExecuteHappyPath:
    """End-to-end success paths."""

    @pytest.fixture
    def tool(self) -> ScalingTestTool:
        return ScalingTestTool()

    @pytest.mark.asyncio
    async def test_scale_up_and_back(self, tool: ScalingTestTool) -> None:
        """Full happy path: scale up, wait, scale back to 1."""
        status_json = '{"applications": {"my-app": {"units": {"my-app/0": {}}}}}'
        scaled_json = (
            '{"applications": {"my-app": {"units": '
            '{"my-app/0": {}, "my-app/1": {}, "my-app/2": {}}}}}'
        )

        def _fake_run_juju(args: list[str], _model: str | None, **_kw: object) -> SimpleNamespace:
            if args[0] == "status" and "--format" in args:
                # _get_unit_count reads json status; first call returns 1 unit,
                # later calls return the scaled unit count.
                if not getattr(_fake_run_juju, "post_scale", False):
                    return _fake_proc(stdout=status_json)
                return _fake_proc(stdout=scaled_json)
            if args[0] == "scale-application":
                _fake_run_juju.post_scale = True  # type: ignore[attr-defined]
                return _fake_proc(returncode=0)
            # Plain `juju status <app>` for report capture.
            return _fake_proc(stdout="model status snapshot")

        with (
            mock.patch("cantrip.agent.tools.scaling.shutil.which", return_value="/usr/bin/juju"),
            mock.patch(
                "cantrip.agent.tools.scaling.juju_subprocess.run_juju",
                side_effect=_fake_run_juju,
            ),
            mock.patch(
                "cantrip.agent.tools.scaling.juju_subprocess.wait_for_app",
                return_value=True,
            ),
        ):
            result = await tool.execute(app="my-app", target_units=3)

        assert result.success
        assert "# Scaling Test Report" in result.output
        assert "Scale Up to 3" in result.output
        assert "Scale Down to 1" in result.output
        assert "**PASS**" in result.output
        assert result.data == {
            "app": "my-app",
            "initial_units": 1,
            "target_units": 3,
            "scale_up_ok": True,
            "scale_down_ok": True,
            "verdict": "pass",
        }

    @pytest.mark.asyncio
    async def test_scale_without_scale_back(self, tool: ScalingTestTool) -> None:
        """``scale_back=False`` skips the scale-down step."""
        with (
            mock.patch("cantrip.agent.tools.scaling.shutil.which", return_value="/usr/bin/juju"),
            mock.patch(
                "cantrip.agent.tools.scaling.juju_subprocess.run_juju",
                return_value=_fake_proc(stdout='{"applications": {"my-app": {"units": {}}}}'),
            ),
            mock.patch(
                "cantrip.agent.tools.scaling.juju_subprocess.wait_for_app",
                return_value=True,
            ),
        ):
            result = await tool.execute(app="my-app", target_units=2, scale_back=False)

        assert result.success
        assert "Scale Down" not in result.output
        assert result.data["scale_down_ok"] is True  # defaults to True when skipped


class TestScalingTestToolExecuteFailures:
    """Failure and fallback paths."""

    @pytest.fixture
    def tool(self) -> ScalingTestTool:
        return ScalingTestTool()

    @pytest.mark.asyncio
    async def test_add_unit_fallback_succeeds(self, tool: ScalingTestTool) -> None:
        """Machine models: scale-application fails, add-unit succeeds."""
        calls: list[list[str]] = []

        def _fake_run_juju(args: list[str], _model: str | None, **_kw: object) -> SimpleNamespace:
            calls.append(args)
            if args[0] == "scale-application":
                return _fake_proc(returncode=1, stderr="unsupported on IAAS")
            if args[0] == "add-unit":
                return _fake_proc(returncode=0)
            if args[0] == "status" and "--format" in args:
                return _fake_proc(
                    stdout='{"applications": {"my-app": {"units": {"my-app/0": {}}}}}'
                )
            return _fake_proc(stdout="status snapshot")

        with (
            mock.patch("cantrip.agent.tools.scaling.shutil.which", return_value="/usr/bin/juju"),
            mock.patch(
                "cantrip.agent.tools.scaling.juju_subprocess.run_juju",
                side_effect=_fake_run_juju,
            ),
            mock.patch(
                "cantrip.agent.tools.scaling.juju_subprocess.wait_for_app",
                return_value=True,
            ),
        ):
            result = await tool.execute(app="my-app", target_units=3, scale_back=False)

        assert result.success
        assert any(c[0] == "add-unit" for c in calls)

    @pytest.mark.asyncio
    async def test_add_unit_fallback_fails(self, tool: ScalingTestTool) -> None:
        """Both scale-application and add-unit fail — returns failure early."""

        def _fake_run_juju(args: list[str], _model: str | None, **_kw: object) -> SimpleNamespace:
            if args[0] == "scale-application":
                return _fake_proc(returncode=1, stderr="no")
            if args[0] == "add-unit":
                return _fake_proc(returncode=1, stderr="unit limit reached")
            if args[0] == "status" and "--format" in args:
                return _fake_proc(
                    stdout='{"applications": {"my-app": {"units": {"my-app/0": {}}}}}'
                )
            return _fake_proc(stdout="status snapshot")

        with (
            mock.patch("cantrip.agent.tools.scaling.shutil.which", return_value="/usr/bin/juju"),
            mock.patch(
                "cantrip.agent.tools.scaling.juju_subprocess.run_juju",
                side_effect=_fake_run_juju,
            ),
        ):
            result = await tool.execute(app="my-app", target_units=3)

        assert not result.success
        assert "unit limit reached" in result.error

    @pytest.mark.asyncio
    async def test_wait_failure_marks_scale_up_failed(self, tool: ScalingTestTool) -> None:
        """If wait-for never reaches active, scale_up_ok is False and verdict is FAIL."""
        with (
            mock.patch("cantrip.agent.tools.scaling.shutil.which", return_value="/usr/bin/juju"),
            mock.patch(
                "cantrip.agent.tools.scaling.juju_subprocess.run_juju",
                return_value=_fake_proc(stdout='{"applications": {"my-app": {"units": {}}}}'),
            ),
            mock.patch(
                "cantrip.agent.tools.scaling.juju_subprocess.wait_for_app",
                return_value=False,
            ),
        ):
            result = await tool.execute(app="my-app", target_units=2, scale_back=False)

        assert not result.success
        assert result.data["scale_up_ok"] is False
        assert result.data["verdict"] == "fail"
        assert "**FAIL**" in result.output


class TestGetUnitCount:
    """Tests for the ``_get_unit_count`` helper."""

    def test_returns_none_when_status_fails(self) -> None:
        with mock.patch(
            "cantrip.agent.tools.scaling.juju_subprocess.run_juju",
            return_value=_fake_proc(returncode=1, stderr="no such app"),
        ):
            assert _get_unit_count("missing-app", None) is None

    def test_returns_none_on_invalid_json(self) -> None:
        with mock.patch(
            "cantrip.agent.tools.scaling.juju_subprocess.run_juju",
            return_value=_fake_proc(stdout="not json"),
        ):
            assert _get_unit_count("my-app", None) is None

    def test_returns_unit_count_from_status(self) -> None:
        payload = '{"applications": {"my-app": {"units": {"my-app/0": {}, "my-app/1": {}}}}}'
        with mock.patch(
            "cantrip.agent.tools.scaling.juju_subprocess.run_juju",
            return_value=_fake_proc(stdout=payload),
        ):
            assert _get_unit_count("my-app", "controller:model") == 2

    def test_returns_zero_when_app_missing(self) -> None:
        with mock.patch(
            "cantrip.agent.tools.scaling.juju_subprocess.run_juju",
            return_value=_fake_proc(stdout='{"applications": {}}'),
        ):
            assert _get_unit_count("my-app", None) == 0
