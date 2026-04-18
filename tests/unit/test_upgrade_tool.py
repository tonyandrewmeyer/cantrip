"""Tests for the upgrade testing tool."""

import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest

from cantrip.agent.tools.upgrade import (
    UpgradeTestTool,
    _check_hook_failures,
    _get_app_status,
)


def _fake_proc(returncode: int = 0, stdout: str = "", stderr: str = "") -> SimpleNamespace:
    return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)


def _status_payload(status: str = "active", units: int = 1) -> str:
    unit_map = {f"my-app/{i}": {"workload-status": {"current": "active"}} for i in range(units)}
    return (
        '{"applications": {"my-app": {'
        f'"application-status": {{"current": "{status}"}}, '
        f'"units": {unit_map}'.replace("'", '"')
        + "}}}"
    )


class TestUpgradeTestToolMetadata:
    def test_tool_name(self) -> None:
        assert UpgradeTestTool().name == "upgrade_test"

    def test_parameters_schema(self) -> None:
        params = UpgradeTestTool().parameters
        props = params["properties"]
        assert {"app", "charm_path", "model", "resources", "timeout"} <= props.keys()
        assert set(params["required"]) == {"app", "charm_path"}

    def test_description_mentions_upgrade(self) -> None:
        assert "upgrade" in UpgradeTestTool().description.lower()


class TestUpgradeTestToolGuards:
    @pytest.fixture
    def tool(self) -> UpgradeTestTool:
        return UpgradeTestTool()

    @pytest.mark.asyncio
    async def test_juju_not_installed(self, tool: UpgradeTestTool) -> None:
        with mock.patch("cantrip.agent.tools.upgrade.shutil.which", return_value=None):
            result = await tool.execute(app="my-app", charm_path="/tmp/x.charm")
        assert not result.success
        assert "juju cli not found" in result.error.lower()

    @pytest.mark.asyncio
    async def test_missing_app(self, tool: UpgradeTestTool) -> None:
        with mock.patch("cantrip.agent.tools.upgrade.shutil.which", return_value="/usr/bin/juju"):
            result = await tool.execute(app="", charm_path="/tmp/x.charm")
        assert not result.success
        assert "app parameter" in result.error

    @pytest.mark.asyncio
    async def test_missing_charm_file(self, tool: UpgradeTestTool, tmp_path: Path) -> None:
        missing = tmp_path / "does-not-exist.charm"
        with mock.patch("cantrip.agent.tools.upgrade.shutil.which", return_value="/usr/bin/juju"):
            result = await tool.execute(app="my-app", charm_path=str(missing))
        assert not result.success
        assert "charm file not found" in result.error.lower()

    @pytest.mark.asyncio
    async def test_application_not_deployed(self, tool: UpgradeTestTool, tmp_path: Path) -> None:
        """Pre-upgrade status is empty → early failure with clear error."""
        charm = tmp_path / "my-app.charm"
        charm.write_bytes(b"stub")

        with (
            mock.patch("cantrip.agent.tools.upgrade.shutil.which", return_value="/usr/bin/juju"),
            mock.patch(
                "cantrip.agent.tools.upgrade.juju_subprocess.run_juju",
                return_value=_fake_proc(returncode=1, stderr="not found"),
            ),
        ):
            result = await tool.execute(app="my-app", charm_path=str(charm))

        assert not result.success
        assert "not deployed" in result.error


class TestUpgradeTestToolExecute:
    @pytest.fixture
    def tool(self) -> UpgradeTestTool:
        return UpgradeTestTool()

    @pytest.fixture
    def charm(self, tmp_path: Path) -> Path:
        path = tmp_path / "my-app.charm"
        path.write_bytes(b"stub")
        return path

    @pytest.mark.asyncio
    async def test_happy_path(self, tool: UpgradeTestTool, charm: Path) -> None:
        """Full upgrade with recovery and no hook failures → PASS."""
        status = {
            "applications": {
                "my-app": {
                    "application-status": {"current": "active"},
                    "units": {"my-app/0": {"workload-status": {"current": "active"}}},
                }
            }
        }

        import json

        def _fake_run_juju(args: list[str], _model: str | None, **_kw: object) -> SimpleNamespace:
            if args[0] == "status":
                return _fake_proc(stdout=json.dumps(status))
            if args[0] == "refresh":
                return _fake_proc(returncode=0)
            if args[0] == "debug-log":
                return _fake_proc(stdout="")
            return _fake_proc()

        with (
            mock.patch("cantrip.agent.tools.upgrade.shutil.which", return_value="/usr/bin/juju"),
            mock.patch(
                "cantrip.agent.tools.upgrade.juju_subprocess.run_juju",
                side_effect=_fake_run_juju,
            ),
            mock.patch(
                "cantrip.agent.tools.upgrade.juju_subprocess.wait_for_app",
                return_value=True,
            ),
        ):
            result = await tool.execute(app="my-app", charm_path=str(charm))

        assert result.success
        assert "**PASS**" in result.output
        assert result.data["verdict"] == "pass"
        assert result.data["recovered"] is True
        assert result.data["status_regressed"] is False
        assert result.data["hook_failures"] == 0

    @pytest.mark.asyncio
    async def test_resources_passed_to_refresh(self, tool: UpgradeTestTool, charm: Path) -> None:
        """``--resource`` flags are forwarded for every provided mapping."""
        import json

        status = {
            "applications": {
                "my-app": {
                    "application-status": {"current": "active"},
                    "units": {"my-app/0": {"workload-status": {"current": "active"}}},
                }
            }
        }

        captured: list[list[str]] = []

        def _fake_run_juju(args: list[str], _model: str | None, **_kw: object) -> SimpleNamespace:
            captured.append(list(args))
            if args[0] == "status":
                return _fake_proc(stdout=json.dumps(status))
            if args[0] == "refresh":
                return _fake_proc(returncode=0)
            if args[0] == "debug-log":
                return _fake_proc(stdout="")
            return _fake_proc()

        with (
            mock.patch("cantrip.agent.tools.upgrade.shutil.which", return_value="/usr/bin/juju"),
            mock.patch(
                "cantrip.agent.tools.upgrade.juju_subprocess.run_juju",
                side_effect=_fake_run_juju,
            ),
            mock.patch(
                "cantrip.agent.tools.upgrade.juju_subprocess.wait_for_app",
                return_value=True,
            ),
        ):
            await tool.execute(
                app="my-app",
                charm_path=str(charm),
                resources={"oci-image": "registry/img:tag"},
            )

        refresh = next(args for args in captured if args[0] == "refresh")
        assert "--resource" in refresh
        assert "oci-image=registry/img:tag" in refresh

    @pytest.mark.asyncio
    async def test_refresh_timeout(self, tool: UpgradeTestTool, charm: Path) -> None:
        import json

        status = {
            "applications": {
                "my-app": {
                    "application-status": {"current": "active"},
                    "units": {"my-app/0": {"workload-status": {"current": "active"}}},
                }
            }
        }

        def _fake_run_juju(args: list[str], _model: str | None, **_kw: object) -> SimpleNamespace:
            if args[0] == "status":
                return _fake_proc(stdout=json.dumps(status))
            if args[0] == "refresh":
                raise subprocess.TimeoutExpired(cmd="juju refresh", timeout=60)
            return _fake_proc()

        with (
            mock.patch("cantrip.agent.tools.upgrade.shutil.which", return_value="/usr/bin/juju"),
            mock.patch(
                "cantrip.agent.tools.upgrade.juju_subprocess.run_juju",
                side_effect=_fake_run_juju,
            ),
        ):
            result = await tool.execute(app="my-app", charm_path=str(charm))

        assert not result.success
        assert "timed out" in result.error.lower()

    @pytest.mark.asyncio
    async def test_refresh_non_zero_exit(self, tool: UpgradeTestTool, charm: Path) -> None:
        import json

        status = {
            "applications": {
                "my-app": {
                    "application-status": {"current": "active"},
                    "units": {"my-app/0": {"workload-status": {"current": "active"}}},
                }
            }
        }

        def _fake_run_juju(args: list[str], _model: str | None, **_kw: object) -> SimpleNamespace:
            if args[0] == "status":
                return _fake_proc(stdout=json.dumps(status))
            if args[0] == "refresh":
                return _fake_proc(returncode=1, stderr="bad charm")
            return _fake_proc()

        with (
            mock.patch("cantrip.agent.tools.upgrade.shutil.which", return_value="/usr/bin/juju"),
            mock.patch(
                "cantrip.agent.tools.upgrade.juju_subprocess.run_juju",
                side_effect=_fake_run_juju,
            ),
        ):
            result = await tool.execute(app="my-app", charm_path=str(charm))

        assert not result.success
        assert "bad charm" in result.error

    @pytest.mark.asyncio
    async def test_regression_detected(self, tool: UpgradeTestTool, charm: Path) -> None:
        """Pre active, post blocked → regression, FAIL verdict."""
        import json

        pre = {
            "applications": {
                "my-app": {
                    "application-status": {"current": "active"},
                    "units": {"my-app/0": {"workload-status": {"current": "active"}}},
                }
            }
        }
        post = {
            "applications": {
                "my-app": {
                    "application-status": {"current": "blocked"},
                    "units": {"my-app/0": {"workload-status": {"current": "blocked"}}},
                }
            }
        }
        status_calls = [pre, post, post]

        def _fake_run_juju(args: list[str], _model: str | None, **_kw: object) -> SimpleNamespace:
            if args[0] == "status":
                return _fake_proc(stdout=json.dumps(status_calls.pop(0)))
            if args[0] == "refresh":
                return _fake_proc(returncode=0)
            if args[0] == "debug-log":
                return _fake_proc(stdout="unit/0 hook failed: upgrade-charm")
            return _fake_proc()

        with (
            mock.patch("cantrip.agent.tools.upgrade.shutil.which", return_value="/usr/bin/juju"),
            mock.patch(
                "cantrip.agent.tools.upgrade.juju_subprocess.run_juju",
                side_effect=_fake_run_juju,
            ),
            mock.patch(
                "cantrip.agent.tools.upgrade.juju_subprocess.wait_for_app",
                return_value=True,
            ),
        ):
            result = await tool.execute(app="my-app", charm_path=str(charm))

        assert not result.success
        assert result.data["status_regressed"] is True
        assert result.data["hook_failures"] >= 1
        assert "REGRESSION" in result.output

    @pytest.mark.asyncio
    async def test_recovery_failure(self, tool: UpgradeTestTool, charm: Path) -> None:
        """Refresh succeeds but wait-for-app times out — FAIL."""
        import json

        status = {
            "applications": {
                "my-app": {
                    "application-status": {"current": "active"},
                    "units": {"my-app/0": {"workload-status": {"current": "active"}}},
                }
            }
        }

        def _fake_run_juju(args: list[str], _model: str | None, **_kw: object) -> SimpleNamespace:
            if args[0] == "status":
                return _fake_proc(stdout=json.dumps(status))
            if args[0] == "refresh":
                return _fake_proc(returncode=0)
            if args[0] == "debug-log":
                return _fake_proc(stdout="")
            return _fake_proc()

        with (
            mock.patch("cantrip.agent.tools.upgrade.shutil.which", return_value="/usr/bin/juju"),
            mock.patch(
                "cantrip.agent.tools.upgrade.juju_subprocess.run_juju",
                side_effect=_fake_run_juju,
            ),
            mock.patch(
                "cantrip.agent.tools.upgrade.juju_subprocess.wait_for_app",
                return_value=False,
            ),
        ):
            result = await tool.execute(app="my-app", charm_path=str(charm))

        assert not result.success
        assert result.data["recovered"] is False
        assert "FAILED" in result.output


class TestGetAppStatus:
    def test_returns_empty_on_non_zero(self) -> None:
        with mock.patch(
            "cantrip.agent.tools.upgrade.juju_subprocess.run_juju",
            return_value=_fake_proc(returncode=1),
        ):
            assert _get_app_status("my-app", None) == {}

    def test_returns_empty_on_bad_json(self) -> None:
        with mock.patch(
            "cantrip.agent.tools.upgrade.juju_subprocess.run_juju",
            return_value=_fake_proc(stdout="not json"),
        ):
            assert _get_app_status("my-app", None) == {}

    def test_returns_app_block(self) -> None:
        payload = '{"applications": {"my-app": {"application-status": {"current": "active"}}}}'
        with mock.patch(
            "cantrip.agent.tools.upgrade.juju_subprocess.run_juju",
            return_value=_fake_proc(stdout=payload),
        ):
            status = _get_app_status("my-app", None)
        assert status == {"application-status": {"current": "active"}}


class TestCheckHookFailures:
    def test_subprocess_error_returns_empty(self) -> None:
        with mock.patch(
            "cantrip.agent.tools.upgrade.juju_subprocess.run_juju",
            side_effect=FileNotFoundError,
        ):
            assert _check_hook_failures("my-app", None) == []

    def test_non_zero_returns_empty(self) -> None:
        with mock.patch(
            "cantrip.agent.tools.upgrade.juju_subprocess.run_juju",
            return_value=_fake_proc(returncode=1),
        ):
            assert _check_hook_failures("my-app", None) == []

    def test_extracts_hook_failures_from_log(self) -> None:
        log = (
            "normal line\n"
            "unit my-app/0: hook failed: install\n"
            "another normal line\n"
            "ERROR: something bad\n"
        )
        with mock.patch(
            "cantrip.agent.tools.upgrade.juju_subprocess.run_juju",
            return_value=_fake_proc(stdout=log),
        ):
            failures = _check_hook_failures("my-app", None)
        assert len(failures) == 2
        assert any("hook failed" in f for f in failures)

    def test_caps_result_to_last_twenty(self) -> None:
        """Guardrail: output is trimmed to last 20 matches."""
        lines = "\n".join(f"unit my-app/{i}: hook failed: x" for i in range(30))
        with mock.patch(
            "cantrip.agent.tools.upgrade.juju_subprocess.run_juju",
            return_value=_fake_proc(stdout=lines),
        ):
            failures = _check_hook_failures("my-app", None)
        assert len(failures) == 20
