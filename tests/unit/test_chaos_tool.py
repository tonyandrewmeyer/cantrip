"""Tests for the chaos testing tool."""

import subprocess
from types import SimpleNamespace
from unittest import mock

import pytest

from cantrip.agent.tools.chaos import _DISRUPTIONS, ChaosTestTool


def _fake_proc(returncode: int = 0, stdout: str = "", stderr: str = "") -> SimpleNamespace:
    return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)


class TestChaosTestToolMetadata:
    def test_tool_name(self) -> None:
        assert ChaosTestTool().name == "chaos_test"

    def test_supported_disruptions(self) -> None:
        assert {
            "kill-unit",
            "remove-relation",
            "scale-down",
            "config-reset",
        } == _DISRUPTIONS

    def test_parameters_schema(self) -> None:
        params = ChaosTestTool().parameters
        props = params["properties"]
        assert {"app", "disruption", "model", "relation", "timeout"} <= props.keys()
        assert set(params["required"]) == {"app", "disruption"}
        assert props["disruption"]["enum"] == sorted(_DISRUPTIONS)


class TestChaosTestToolExecuteGuards:
    @pytest.fixture
    def tool(self) -> ChaosTestTool:
        return ChaosTestTool()

    @pytest.mark.asyncio
    async def test_juju_not_installed(self, tool: ChaosTestTool) -> None:
        with mock.patch("cantrip.agent.tools.chaos.shutil.which", return_value=None):
            result = await tool.execute(app="my-app", disruption="kill-unit")
        assert not result.success
        assert "juju cli not found" in result.error.lower()

    @pytest.mark.asyncio
    async def test_missing_app(self, tool: ChaosTestTool) -> None:
        with mock.patch("cantrip.agent.tools.chaos.shutil.which", return_value="/usr/bin/juju"):
            result = await tool.execute(app="", disruption="kill-unit")
        assert not result.success
        assert "app parameter" in result.error

    @pytest.mark.asyncio
    async def test_unknown_disruption(self, tool: ChaosTestTool) -> None:
        with mock.patch("cantrip.agent.tools.chaos.shutil.which", return_value="/usr/bin/juju"):
            result = await tool.execute(app="my-app", disruption="kaboom")
        assert not result.success
        assert "unknown disruption" in result.error.lower()

    @pytest.mark.asyncio
    async def test_pre_status_failure(self, tool: ChaosTestTool) -> None:
        with (
            mock.patch("cantrip.agent.tools.chaos.shutil.which", return_value="/usr/bin/juju"),
            mock.patch(
                "cantrip.agent.tools.chaos.juju_subprocess.run_juju",
                return_value=_fake_proc(returncode=1, stderr="no such app"),
            ),
        ):
            result = await tool.execute(app="my-app", disruption="kill-unit")
        assert not result.success
        assert "failed to get status" in result.error.lower()


class TestChaosTestToolDisruptions:
    """Execute each disruption path end-to-end, mocking Juju calls."""

    @pytest.fixture
    def tool(self) -> ChaosTestTool:
        return ChaosTestTool()

    def _run_execute(
        self,
        tool: ChaosTestTool,
        run_juju_side_effect,
        recovery: bool = True,
        **execute_kwargs,
    ):
        async def _call() -> object:
            with (
                mock.patch("cantrip.agent.tools.chaos.shutil.which", return_value="/usr/bin/juju"),
                mock.patch(
                    "cantrip.agent.tools.chaos.juju_subprocess.run_juju",
                    side_effect=run_juju_side_effect,
                ),
                mock.patch.object(ChaosTestTool, "_wait_for_recovery", return_value=recovery),
            ):
                return await tool.execute(**execute_kwargs)

        import asyncio

        return asyncio.run(_call())

    def test_kill_unit_happy_path(self, tool: ChaosTestTool) -> None:
        def _run_juju(args: list[str], _model: str | None, **_kw: object) -> SimpleNamespace:
            if args[0] == "remove-unit":
                return _fake_proc(returncode=0)
            return _fake_proc(stdout="status-snapshot")

        result = self._run_execute(
            tool, _run_juju, recovery=True, app="my-app", disruption="kill-unit"
        )
        assert result.success
        assert "Removed unit my-app/0" in result.output
        assert result.data == {
            "app": "my-app",
            "disruption": "kill-unit",
            "recovered": True,
        }

    def test_kill_unit_failure(self, tool: ChaosTestTool) -> None:
        def _run_juju(args: list[str], _model: str | None, **_kw: object) -> SimpleNamespace:
            if args[0] == "remove-unit":
                return _fake_proc(returncode=1, stderr="not allowed")
            return _fake_proc(stdout="ok")

        result = self._run_execute(tool, _run_juju, app="my-app", disruption="kill-unit")
        assert not result.success
        assert "failed to remove unit" in result.error.lower()

    def test_remove_relation_requires_relation(self, tool: ChaosTestTool) -> None:
        def _run_juju(_args: list[str], _model: str | None, **_kw: object) -> SimpleNamespace:
            return _fake_proc(stdout="ok")

        result = self._run_execute(tool, _run_juju, app="my-app", disruption="remove-relation")
        assert not result.success
        assert "relation parameter required" in result.error.lower()

    def test_remove_relation_happy_path(self, tool: ChaosTestTool) -> None:
        captured: list[list[str]] = []

        def _run_juju(args: list[str], _model: str | None, **_kw: object) -> SimpleNamespace:
            captured.append(list(args))
            if args[0] == "remove-relation":
                return _fake_proc(returncode=0)
            return _fake_proc(stdout="status-snapshot")

        result = self._run_execute(
            tool,
            _run_juju,
            app="my-app",
            disruption="remove-relation",
            relation="my-app:db postgres:db",
        )
        assert result.success
        remove = next(c for c in captured if c[0] == "remove-relation")
        assert remove[1:] == ["my-app:db", "postgres:db"]

    def test_remove_relation_failure(self, tool: ChaosTestTool) -> None:
        def _run_juju(args: list[str], _model: str | None, **_kw: object) -> SimpleNamespace:
            if args[0] == "remove-relation":
                return _fake_proc(returncode=1, stderr="no such relation")
            return _fake_proc(stdout="ok")

        result = self._run_execute(
            tool,
            _run_juju,
            app="my-app",
            disruption="remove-relation",
            relation="my-app:db postgres:db",
        )
        assert not result.success
        assert "failed to remove relation" in result.error.lower()

    def test_scale_down_happy_path(self, tool: ChaosTestTool) -> None:
        """scale-application 0 then scale-application 1."""
        calls: list[list[str]] = []

        def _run_juju(args: list[str], _model: str | None, **_kw: object) -> SimpleNamespace:
            calls.append(list(args))
            if args[0] == "scale-application":
                return _fake_proc(returncode=0)
            return _fake_proc(stdout="status-snapshot")

        result = self._run_execute(tool, _run_juju, app="my-app", disruption="scale-down")
        assert result.success
        scale_calls = [c for c in calls if c[0] == "scale-application"]
        assert scale_calls == [
            ["scale-application", "my-app", "0"],
            ["scale-application", "my-app", "1"],
        ]

    def test_scale_down_falls_back_to_remove_unit(self, tool: ChaosTestTool) -> None:
        """IAAS: scale-application fails, remove-unit + add-unit restore."""

        def _run_juju(args: list[str], _model: str | None, **_kw: object) -> SimpleNamespace:
            if args[0] == "scale-application":
                return _fake_proc(returncode=1, stderr="unsupported on IAAS")
            if args[0] == "remove-unit":
                return _fake_proc(returncode=0)
            if args[0] == "add-unit":
                return _fake_proc(returncode=0)
            return _fake_proc(stdout="status-snapshot")

        result = self._run_execute(tool, _run_juju, app="my-app", disruption="scale-down")
        assert result.success
        assert "Scaled my-app down to 0" in result.output

    def test_scale_down_failure(self, tool: ChaosTestTool) -> None:
        """Both scale-application and remove-unit fail — disruption errors out."""

        def _run_juju(args: list[str], _model: str | None, **_kw: object) -> SimpleNamespace:
            if args[0] in {"scale-application", "remove-unit"}:
                return _fake_proc(returncode=1, stderr="permission denied")
            return _fake_proc(stdout="status-snapshot")

        result = self._run_execute(tool, _run_juju, app="my-app", disruption="scale-down")
        assert not result.success
        assert "failed to scale down" in result.error.lower()

    def test_config_reset_happy_path(self, tool: ChaosTestTool) -> None:
        def _run_juju(args: list[str], _model: str | None, **_kw: object) -> SimpleNamespace:
            if args[0] == "config":
                return _fake_proc(returncode=0)
            return _fake_proc(stdout="status-snapshot")

        result = self._run_execute(tool, _run_juju, app="my-app", disruption="config-reset")
        assert result.success
        assert "Reset all config" in result.output

    def test_config_reset_failure(self, tool: ChaosTestTool) -> None:
        def _run_juju(args: list[str], _model: str | None, **_kw: object) -> SimpleNamespace:
            if args[0] == "config":
                return _fake_proc(returncode=1, stderr="charm busy")
            return _fake_proc(stdout="status-snapshot")

        result = self._run_execute(tool, _run_juju, app="my-app", disruption="config-reset")
        assert not result.success
        assert "failed to reset config" in result.error.lower()

    def test_disruption_timeout(self, tool: ChaosTestTool) -> None:
        """If a juju subprocess call times out during disruption, tool reports it."""

        def _run_juju(args: list[str], _model: str | None, **_kw: object) -> SimpleNamespace:
            if args[0] == "remove-unit":
                raise subprocess.TimeoutExpired(cmd="juju remove-unit", timeout=60)
            return _fake_proc(stdout="status-snapshot")

        result = self._run_execute(tool, _run_juju, app="my-app", disruption="kill-unit")
        assert not result.success
        assert "timed out" in result.error.lower()

    def test_recovery_failure_marks_overall_fail(self, tool: ChaosTestTool) -> None:
        def _run_juju(args: list[str], _model: str | None, **_kw: object) -> SimpleNamespace:
            if args[0] == "remove-unit":
                return _fake_proc(returncode=0)
            return _fake_proc(stdout="status-snapshot")

        result = self._run_execute(
            tool, _run_juju, recovery=False, app="my-app", disruption="kill-unit"
        )
        assert not result.success
        assert result.data["recovered"] is False
        assert "FAILED" in result.output


class TestWaitForRecovery:
    def test_returns_true_on_zero_exit(self) -> None:
        with mock.patch(
            "cantrip.agent.tools.chaos.subprocess.run",
            return_value=_fake_proc(returncode=0),
        ):
            assert ChaosTestTool._wait_for_recovery("my-app", None, 30) is True

    def test_returns_false_on_non_zero(self) -> None:
        with mock.patch(
            "cantrip.agent.tools.chaos.subprocess.run",
            return_value=_fake_proc(returncode=1),
        ):
            assert ChaosTestTool._wait_for_recovery("my-app", None, 30) is False

    def test_returns_false_on_timeout(self) -> None:
        with mock.patch(
            "cantrip.agent.tools.chaos.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="juju wait-for", timeout=30),
        ):
            assert ChaosTestTool._wait_for_recovery("my-app", None, 30) is False

    def test_returns_false_on_missing_binary(self) -> None:
        with mock.patch(
            "cantrip.agent.tools.chaos.subprocess.run",
            side_effect=FileNotFoundError,
        ):
            assert ChaosTestTool._wait_for_recovery("my-app", None, 30) is False

    def test_model_flag_forwarded(self) -> None:
        with mock.patch(
            "cantrip.agent.tools.chaos.subprocess.run",
            return_value=_fake_proc(returncode=0),
        ) as run:
            ChaosTestTool._wait_for_recovery("my-app", "controller:prod", 30)

        cmd = run.call_args[0][0]
        assert "--model" in cmd and cmd[cmd.index("--model") + 1] == "controller:prod"
