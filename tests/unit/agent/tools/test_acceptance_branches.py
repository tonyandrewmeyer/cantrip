"""Branch-coverage backfill for ``cantrip.agent.tools.acceptance``.

The base ``test_acceptance_tools.py`` covers happy-paths and tool
metadata.  This file fills the failure / fallback / shell-out branches
the existing suite skips:

- ``_verify_relation_data`` model arg, subprocess errors, JSON failures,
  endpoint-not-found
- ``_get_unit_address`` rc != 0 path, valid/invalid addresses
- ``_generate_action_params`` non-dict spec, integer with no minimum,
  array shape
- ``ActionExerciserTool`` non-dict action spec, timeout, model arg
- ``RelationSmokeTool`` shell guards, deploy/relate/settle/no-partner
  branches
- ``WorkloadEndpointTool`` end-to-end probe loop with explicit /
  discovered endpoints, ``_discover_endpoints`` config-port path,
  ``_probe_http`` and ``_probe_tcp`` shell branches
- ``ConfigVariationTool`` set-failed, set-timeout, reset-timeout,
  non-dict spec
- ``ConfigUnderLoadTool`` non-OK status, probe exception, config-with-model,
  reset-with-model
- ``AcceptanceReportTool`` non-existent dir, lifecycle section
"""

from __future__ import annotations

import json
import pathlib
import subprocess
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from cantrip.agent.tools.acceptance import (
    AcceptanceReportTool,
    ActionExerciserTool,
    ConfigUnderLoadTool,
    ConfigVariationTool,
    RelationSmokeTool,
    WorkloadEndpointTool,
    _generate_action_params,
    _get_unit_address,
    _verify_relation_data,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _proc(returncode: int = 0, stdout: str = "", stderr: str = "") -> MagicMock:
    p = MagicMock()
    p.returncode = returncode
    p.stdout = stdout
    p.stderr = stderr
    return p


# ---------------------------------------------------------------------------
# _verify_relation_data
# ---------------------------------------------------------------------------


class TestVerifyRelationDataBranches:
    """Branches not covered by ``test_acceptance_tools.TestVerifyRelationData``."""

    def test_model_arg_is_threaded_into_juju_command(self) -> None:
        # ``model`` extends the juju args; the command is otherwise the
        # same shape we already verify in the happy-path tests.
        with patch(
            "subprocess.run",
            return_value=_proc(returncode=0, stdout=json.dumps({"u/0": {}})),
        ) as run:
            has_data, _ = _verify_relation_data("u/0", "db", model="dev")
        # First positional arg is the juju command list.
        cmd = run.call_args.args[0]
        assert cmd == [
            "juju",
            "show-unit",
            "u/0",
            "--format",
            "json",
            "--model",
            "dev",
        ]
        assert has_data is False

    def test_subprocess_timeout_returns_false(self) -> None:
        with patch(
            "subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="juju", timeout=1),
        ):
            has_data, notes = _verify_relation_data("u/0", "db", None)
        assert has_data is False
        assert "Could not read" in notes

    def test_subprocess_oserror_returns_false(self) -> None:
        with patch("subprocess.run", side_effect=OSError("eperm")):
            has_data, notes = _verify_relation_data("u/0", "db", None)
        assert has_data is False
        assert "Could not read" in notes

    def test_invalid_json_returns_false(self) -> None:
        with patch("subprocess.run", return_value=_proc(returncode=0, stdout="not json")):
            has_data, notes = _verify_relation_data("u/0", "db", None)
        assert has_data is False
        assert "Invalid JSON" in notes

    def test_endpoint_skipped_when_name_does_not_match(self) -> None:
        payload = {
            "u/0": {
                "relation-info": [
                    {
                        "endpoint": "other",
                        "application-data": {"key": "value"},
                        "related-units": {},
                    },
                ]
            }
        }
        with patch(
            "subprocess.run",
            return_value=_proc(returncode=0, stdout=json.dumps(payload)),
        ):
            has_data, notes = _verify_relation_data("u/0", "db", None)
        assert has_data is False
        assert "not found" in notes

    def test_meaningful_unit_data_is_detected(self) -> None:
        payload = {
            "u/0": {
                "relation-info": [
                    {
                        "endpoint": "db",
                        "application-data": {},
                        "related-units": {
                            "pg/0": {
                                "data": {
                                    "ingress-address": "10.0.0.1",
                                    "username": "u",
                                }
                            }
                        },
                    }
                ]
            }
        }
        with patch(
            "subprocess.run",
            return_value=_proc(returncode=0, stdout=json.dumps(payload)),
        ):
            has_data, notes = _verify_relation_data("u/0", "db", None)
        assert has_data is True
        assert "username" in notes


# ---------------------------------------------------------------------------
# _get_unit_address
# ---------------------------------------------------------------------------


class TestGetUnitAddress:
    """``_get_unit_address`` failure / parse branches."""

    def test_returns_none_on_juju_failure(self) -> None:
        with patch(
            "cantrip.agent.tools.acceptance.juju_subprocess.run_juju",
            return_value=_proc(returncode=1),
        ):
            assert _get_unit_address("app", None) is None

    def test_picks_first_unit_address(self) -> None:
        payload = {
            "applications": {
                "app": {
                    "units": {
                        "app/0": {"address": "10.0.0.1"},
                        "app/1": {"address": "10.0.0.2"},
                    }
                }
            }
        }
        with patch(
            "cantrip.agent.tools.acceptance.juju_subprocess.run_juju",
            return_value=_proc(returncode=0, stdout=json.dumps(payload)),
        ):
            assert _get_unit_address("app", None) == "10.0.0.1"

    def test_returns_none_when_units_lack_address(self) -> None:
        payload = {"applications": {"app": {"units": {"app/0": {}}}}}
        with patch(
            "cantrip.agent.tools.acceptance.juju_subprocess.run_juju",
            return_value=_proc(returncode=0, stdout=json.dumps(payload)),
        ):
            assert _get_unit_address("app", None) is None

    def test_returns_none_on_invalid_json(self) -> None:
        with patch(
            "cantrip.agent.tools.acceptance.juju_subprocess.run_juju",
            return_value=_proc(returncode=0, stdout="not json"),
        ):
            assert _get_unit_address("app", None) is None


# ---------------------------------------------------------------------------
# _generate_action_params
# ---------------------------------------------------------------------------


class TestGenerateActionParamsBranches:
    """Defensive shapes the existing suite skips."""

    def test_non_dict_properties_returns_empty(self) -> None:
        assert _generate_action_params({"params": "not a dict"}) == {}

    def test_non_dict_spec_for_an_option_is_skipped(self) -> None:
        assert _generate_action_params({"params": {"x": "not a dict"}}) == {}

    def test_integer_without_minimum_renders_one(self) -> None:
        # Integer with no minimum / default falls through to ``"1"``.
        assert _generate_action_params({"params": {"n": {"type": "integer"}}}) == {"n": "1"}

    def test_array_type_renders_empty_list_literal(self) -> None:
        assert _generate_action_params({"params": {"items": {"type": "array"}}}) == {"items": "[]"}


# ---------------------------------------------------------------------------
# ActionExerciserTool — non-dict spec, timeout, model
# ---------------------------------------------------------------------------


class TestActionExerciserBranches:
    """Branches in ``ActionExerciserTool.execute`` skipped by the base suite."""

    @pytest.mark.asyncio
    async def test_non_dict_spec_is_normalised(self, tmp_path: pathlib.Path) -> None:
        # ``actions:\n  go: yes`` parses to ``{"go": True}`` — non-dict.
        # The tool must still attempt to run it (with empty params).
        (tmp_path / "charmcraft.yaml").write_text("name: test-charm\nactions:\n  go: ok-string\n")
        with (
            patch("shutil.which", return_value="/usr/bin/juju"),
            patch("subprocess.run", return_value=_proc(returncode=0, stdout="{}")),
        ):
            result = await ActionExerciserTool().execute(app="t", path=str(tmp_path))
        assert result.success is True
        assert result.data["actions_tested"] == 1

    @pytest.mark.asyncio
    async def test_model_arg_is_appended(self, tmp_path: pathlib.Path) -> None:
        (tmp_path / "charmcraft.yaml").write_text(
            "name: test-charm\nactions:\n  go: {description: ok}\n"
        )
        captured: list[list[str]] = []

        def _mock_run(cmd: list[str], **_kwargs: Any) -> MagicMock:
            captured.append(cmd)
            return _proc(returncode=0, stdout="{}")

        with (
            patch("shutil.which", return_value="/usr/bin/juju"),
            patch("subprocess.run", side_effect=_mock_run),
        ):
            await ActionExerciserTool().execute(
                app="t",
                path=str(tmp_path),
                model="dev",
            )
        # The subprocess call carries ``--model dev`` after the action args.
        assert any("--model" in cmd and "dev" in cmd for cmd in captured)

    @pytest.mark.asyncio
    async def test_timeout_during_action_is_recorded(self, tmp_path: pathlib.Path) -> None:
        (tmp_path / "charmcraft.yaml").write_text(
            "name: test-charm\nactions:\n  go: {description: ok}\n"
        )
        with (
            patch("shutil.which", return_value="/usr/bin/juju"),
            patch(
                "subprocess.run",
                side_effect=subprocess.TimeoutExpired(cmd="juju", timeout=1),
            ),
        ):
            result = await ActionExerciserTool().execute(
                app="t",
                path=str(tmp_path),
                timeout=5,
            )
        # One result was recorded with the ``timeout`` status.
        assert any(r["status"] == "timeout" for r in result.data["results"])
        assert "Timed out" in result.data["results"][0]["output"]

    @pytest.mark.asyncio
    async def test_action_with_params_appends_to_command(self, tmp_path: pathlib.Path) -> None:
        (tmp_path / "charmcraft.yaml").write_text(
            "name: test-charm\n"
            "actions:\n"
            "  go:\n"
            "    params:\n"
            "      name:\n"
            "        type: string\n"
            "        default: hello\n"
        )
        captured: list[list[str]] = []

        def _mock_run(cmd: list[str], **_kwargs: Any) -> MagicMock:
            captured.append(cmd)
            return _proc(returncode=0, stdout="{}")

        with (
            patch("shutil.which", return_value="/usr/bin/juju"),
            patch("subprocess.run", side_effect=_mock_run),
        ):
            await ActionExerciserTool().execute(app="t", path=str(tmp_path))
        # The juju run command should carry ``name=hello`` in its arg list.
        assert any("name=hello" in c for cmd in captured for c in cmd)

    @pytest.mark.asyncio
    async def test_action_failure_marks_overall_failure(self, tmp_path: pathlib.Path) -> None:
        (tmp_path / "charmcraft.yaml").write_text(
            "name: test-charm\nactions:\n  go: {description: ok}\n"
        )
        with (
            patch("shutil.which", return_value="/usr/bin/juju"),
            patch("subprocess.run", return_value=_proc(returncode=1, stderr="boom")),
        ):
            result = await ActionExerciserTool().execute(app="t", path=str(tmp_path))
        assert result.success is False
        assert any(r["status"] == "failed" for r in result.data["results"])


# ---------------------------------------------------------------------------
# RelationSmokeTool — full path
# ---------------------------------------------------------------------------


class TestToolMetadata:
    """Description property accessors close the description-string branches."""

    def test_descriptions_are_non_empty(self) -> None:
        assert ActionExerciserTool().description
        assert RelationSmokeTool().description
        assert WorkloadEndpointTool().description
        assert ConfigVariationTool().description
        assert ConfigUnderLoadTool().description
        assert AcceptanceReportTool().description


class TestRelationSmokeBranches:
    """RelationSmokeTool deploy/relate/settle/databag branches."""

    @pytest.mark.asyncio
    async def test_provides_role_is_recognised(self, tmp_path: pathlib.Path) -> None:
        # ``provides:`` interfaces are also exercised — known partner
        # routes through the same deploy/relate flow.
        (tmp_path / "charmcraft.yaml").write_text(
            "name: t\nprovides:\n  ingress:\n    interface: ingress\n"
        )
        with (
            patch("shutil.which", return_value="/usr/bin/juju"),
            patch(
                "cantrip.agent.tools.acceptance.juju_subprocess.run_juju",
                return_value=_proc(returncode=0),
            ),
            patch(
                "cantrip.agent.tools.acceptance.juju_subprocess.wait_for_app",
                return_value=True,
            ),
            patch(
                "cantrip.agent.tools.acceptance._common._verify_relation_data",
                return_value=(True, "App data keys: app-data"),
            ),
        ):
            result = await RelationSmokeTool().execute(app="t", path=str(tmp_path))
        assert result.success is True
        assert any(r["role"] == "provides" for r in result.data["results"])

    @pytest.mark.asyncio
    async def test_no_juju_short_circuits(self) -> None:
        with patch("shutil.which", return_value=None):
            result = await RelationSmokeTool().execute(app="t")
        assert result.success is False
        assert "juju CLI not found" in (result.error or "")

    @pytest.mark.asyncio
    async def test_skip_endpoints(self, tmp_path: pathlib.Path) -> None:
        (tmp_path / "charmcraft.yaml").write_text(
            "name: t\nrequires:\n  db:\n    interface: pgsql\n"
        )
        with patch("shutil.which", return_value="/usr/bin/juju"):
            result = await RelationSmokeTool().execute(
                app="t",
                path=str(tmp_path),
                skip_endpoints=["db"],
            )
        assert result.data["endpoints_tested"] == 0

    @pytest.mark.asyncio
    async def test_unknown_interface_is_skipped(self, tmp_path: pathlib.Path) -> None:
        (tmp_path / "charmcraft.yaml").write_text(
            "name: t\nrequires:\n  weird:\n    interface: something-novel\n"
        )
        with patch("shutil.which", return_value="/usr/bin/juju"):
            result = await RelationSmokeTool().execute(app="t", path=str(tmp_path))
        # No known partner — recorded but skipped.
        assert result.data["endpoints_tested"] == 0
        assert any(r["notes"].startswith("No known partner") for r in result.data["results"])

    @pytest.mark.asyncio
    async def test_relate_failure_is_recorded(self, tmp_path: pathlib.Path) -> None:
        (tmp_path / "charmcraft.yaml").write_text(
            "name: t\nrequires:\n  db:\n    interface: pgsql\n"
        )
        with (
            patch("shutil.which", return_value="/usr/bin/juju"),
            patch(
                "cantrip.agent.tools.acceptance.juju_subprocess.run_juju",
                return_value=_proc(returncode=1, stderr="not allowed"),
            ),
        ):
            result = await RelationSmokeTool().execute(app="t", path=str(tmp_path))
        assert result.success is False
        assert any(r["status"] == "failed" for r in result.data["results"])

    @pytest.mark.asyncio
    async def test_existing_relation_continues(self, tmp_path: pathlib.Path) -> None:
        # ``stderr`` containing "already exists" must not abort — the
        # tool falls through to settle + databag verification.
        (tmp_path / "charmcraft.yaml").write_text(
            "name: t\nrequires:\n  db:\n    interface: pgsql\n"
        )
        with (
            patch("shutil.which", return_value="/usr/bin/juju"),
            patch(
                "cantrip.agent.tools.acceptance.juju_subprocess.run_juju",
                return_value=_proc(returncode=1, stderr="relation already exists"),
            ),
            patch(
                "cantrip.agent.tools.acceptance.juju_subprocess.wait_for_app",
                return_value=True,
            ),
            patch(
                "cantrip.agent.tools.acceptance._common._verify_relation_data",
                return_value=(True, "App data keys: foo"),
            ),
        ):
            result = await RelationSmokeTool().execute(app="t", path=str(tmp_path))
        assert result.success is True
        assert any(r["status"] == "pass" for r in result.data["results"])

    @pytest.mark.asyncio
    async def test_relate_timeout_is_recorded(self, tmp_path: pathlib.Path) -> None:
        (tmp_path / "charmcraft.yaml").write_text(
            "name: t\nrequires:\n  db:\n    interface: pgsql\n"
        )
        with (
            patch("shutil.which", return_value="/usr/bin/juju"),
            patch(
                "cantrip.agent.tools.acceptance.juju_subprocess.run_juju",
                side_effect=subprocess.TimeoutExpired(cmd="juju", timeout=1),
            ),
        ):
            result = await RelationSmokeTool().execute(app="t", path=str(tmp_path))
        assert any(r["status"] == "timeout" for r in result.data["results"])

    @pytest.mark.asyncio
    async def test_settled_but_databag_empty(self, tmp_path: pathlib.Path) -> None:
        (tmp_path / "charmcraft.yaml").write_text(
            "name: t\nrequires:\n  db:\n    interface: pgsql\n"
        )
        with (
            patch("shutil.which", return_value="/usr/bin/juju"),
            patch(
                "cantrip.agent.tools.acceptance.juju_subprocess.run_juju",
                return_value=_proc(returncode=0),
            ),
            patch(
                "cantrip.agent.tools.acceptance.juju_subprocess.wait_for_app",
                return_value=True,
            ),
            patch(
                "cantrip.agent.tools.acceptance._common._verify_relation_data",
                return_value=(False, "address-only"),
            ),
        ):
            result = await RelationSmokeTool().execute(app="t", path=str(tmp_path))
        # Settled but databag empty — still pass overall (the integration
        # is up), but with a "but address-only" note.
        assert result.success is True
        assert any("address-only" in r["notes"] for r in result.data["results"])

    @pytest.mark.asyncio
    async def test_did_not_settle(self, tmp_path: pathlib.Path) -> None:
        (tmp_path / "charmcraft.yaml").write_text(
            "name: t\nrequires:\n  db:\n    interface: pgsql\n"
        )
        with (
            patch("shutil.which", return_value="/usr/bin/juju"),
            patch(
                "cantrip.agent.tools.acceptance.juju_subprocess.run_juju",
                return_value=_proc(returncode=0),
            ),
            patch(
                "cantrip.agent.tools.acceptance.juju_subprocess.wait_for_app",
                return_value=False,
            ),
        ):
            result = await RelationSmokeTool().execute(app="t", path=str(tmp_path))
        assert result.success is False
        assert any(r["notes"] == "Did not settle" for r in result.data["results"])


# ---------------------------------------------------------------------------
# WorkloadEndpointTool
# ---------------------------------------------------------------------------


class TestWorkloadEndpointBranches:
    """WorkloadEndpointTool execute/discover/probe branches."""

    @pytest.mark.asyncio
    async def test_no_juju_short_circuits(self) -> None:
        with patch("shutil.which", return_value=None):
            result = await WorkloadEndpointTool().execute(app="t")
        assert result.success is False

    @pytest.mark.asyncio
    async def test_explicit_endpoints_with_url(self) -> None:
        # Bypass discovery by passing explicit endpoints.
        with (
            patch("shutil.which", return_value="/usr/bin/juju"),
            patch(
                "cantrip.agent.tools.acceptance.juju_subprocess.run_juju",
                return_value=_proc(returncode=0, stdout="{}"),
            ),
            patch.object(
                WorkloadEndpointTool,
                "_probe_http",
                return_value={
                    "status": "pass",
                    "response_time": "0.1s",
                    "notes": "HTTP 200",
                },
            ),
        ):
            result = await WorkloadEndpointTool().execute(
                app="t",
                endpoints=[{"url": "http://h:8080/ok", "protocol": "http"}],
            )
        assert result.success is True
        assert result.data["endpoints_tested"] == 1

    @pytest.mark.asyncio
    async def test_endpoint_with_port_resolves_to_url(self) -> None:
        with (
            patch("shutil.which", return_value="/usr/bin/juju"),
            patch(
                "cantrip.agent.tools.acceptance._common._get_unit_address",
                return_value="10.0.0.1",
            ),
            patch.object(
                WorkloadEndpointTool,
                "_probe_http",
                return_value={
                    "status": "pass",
                    "response_time": "0.1s",
                    "notes": "HTTP 200",
                },
            ),
        ):
            result = await WorkloadEndpointTool().execute(
                app="t",
                endpoints=[{"port": 8080, "protocol": "http"}],
            )
        assert result.success is True
        # The probe URL was synthesised from unit_addr + port.
        assert any("http://10.0.0.1:8080" in r["endpoint"] for r in result.data["results"])

    @pytest.mark.asyncio
    async def test_endpoint_without_url_or_address_is_skipped(self) -> None:
        with (
            patch("shutil.which", return_value="/usr/bin/juju"),
            patch(
                "cantrip.agent.tools.acceptance._common._get_unit_address",
                return_value=None,
            ),
        ):
            result = await WorkloadEndpointTool().execute(
                app="t",
                endpoints=[{"port": 8080, "protocol": "http"}],
            )
        # No URL could be built — recorded as "skipped".
        assert any(r["status"] == "skipped" for r in result.data["results"])

    @pytest.mark.asyncio
    async def test_tcp_protocol_routes_to_probe_tcp(self) -> None:
        with (
            patch("shutil.which", return_value="/usr/bin/juju"),
            patch(
                "cantrip.agent.tools.acceptance._common._get_unit_address",
                return_value="10.0.0.1",
            ),
            patch.object(
                WorkloadEndpointTool,
                "_probe_tcp",
                return_value={
                    "status": "pass",
                    "response_time": "—",
                    "notes": "Port open",
                },
            ) as probe_tcp,
        ):
            await WorkloadEndpointTool().execute(
                app="t",
                endpoints=[{"port": 8080, "protocol": "tcp"}],
            )
        probe_tcp.assert_called_once()


class TestDiscoverEndpoints:
    """``WorkloadEndpointTool._discover_endpoints`` config-port path."""

    def test_no_metadata_returns_empty(self, tmp_path: pathlib.Path) -> None:
        # Empty directory has no charm files; helper returns [].
        assert WorkloadEndpointTool._discover_endpoints(str(tmp_path), None) == []

    def test_picks_up_config_port_options(self, tmp_path: pathlib.Path) -> None:
        (tmp_path / "charmcraft.yaml").write_text(
            "name: t\n"
            "config:\n"
            "  options:\n"
            "    server-port:\n"
            "      type: int\n"
            "      default: 8000\n"
            "    other-key:\n"
            "      type: string\n"
            "      default: hi\n"
        )
        probes = WorkloadEndpointTool._discover_endpoints(str(tmp_path), "10.0.0.1")
        assert any(p.get("port") == 8000 for p in probes)
        # Health-path probes must accompany the discovered port.
        assert any("/health" in p.get("url", "") for p in probes)

    def test_non_dict_container_spec_is_skipped(self, tmp_path: pathlib.Path) -> None:
        # ``containers:\n  app: yes`` parses to ``{"app": True}`` —
        # non-dict, the discovery loop must skip rather than crash.
        (tmp_path / "charmcraft.yaml").write_text("name: t\ncontainers:\n  app: ok-string\n")
        probes = WorkloadEndpointTool._discover_endpoints(str(tmp_path), "10.0.0.1")
        assert probes == []

    def test_non_dict_config_option_is_skipped(self, tmp_path: pathlib.Path) -> None:
        (tmp_path / "charmcraft.yaml").write_text(
            "name: t\nconfig:\n  options:\n    bare: ok-string\n"
        )
        probes = WorkloadEndpointTool._discover_endpoints(str(tmp_path), "10.0.0.1")
        assert probes == []

    def test_dedupe_when_port_appears_twice(self, tmp_path: pathlib.Path) -> None:
        # ``server-port`` config plus a container declaring the same port.
        (tmp_path / "charmcraft.yaml").write_text(
            "name: t\n"
            "containers:\n"
            "  app:\n"
            "    ports:\n"
            "      - target: 8000\n"
            "config:\n"
            "  options:\n"
            "    listen-port:\n"
            "      type: int\n"
            "      default: 8000\n"
        )
        probes = WorkloadEndpointTool._discover_endpoints(str(tmp_path), "10.0.0.1")
        # Dedup on port for health probes — 8000 must appear only once
        # in the URL set.
        health_urls = [p.get("url") for p in probes if p.get("url")]
        assert health_urls.count("http://10.0.0.1:8000/health") == 1


class TestProbeHttp:
    """`_probe_http` shell branches."""

    def test_success_parses_status_and_time(self) -> None:
        result = WorkloadEndpointTool._probe_http("http://h/", timeout=5)
        with patch(
            "subprocess.run",
            return_value=_proc(returncode=0, stdout="200 0.123"),
        ):
            result = WorkloadEndpointTool._probe_http("http://h/", timeout=5)
        assert result["status"] == "pass"
        assert result["response_time"] == "0.123s"
        assert "HTTP 200" in result["notes"]

    def test_4xx_is_failure(self) -> None:
        with patch(
            "subprocess.run",
            return_value=_proc(returncode=0, stdout="404 0.05"),
        ):
            result = WorkloadEndpointTool._probe_http("http://h/", timeout=5)
        assert result["status"] == "failed"
        assert "HTTP 404" in result["notes"]

    def test_curl_output_without_time(self) -> None:
        with patch("subprocess.run", return_value=_proc(returncode=0, stdout="200")):
            result = WorkloadEndpointTool._probe_http("http://h/", timeout=5)
        assert result["status"] == "pass"
        assert result["response_time"] == "—"

    def test_subprocess_error_is_caught(self) -> None:
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="curl", timeout=1)):
            result = WorkloadEndpointTool._probe_http("http://h/", timeout=5)
        assert result["status"] == "failed"
        assert "Probe error" in result["notes"]


class TestProbeTcp:
    """`_probe_tcp` shell branches."""

    def test_missing_host_or_port_is_skipped(self) -> None:
        result = WorkloadEndpointTool._probe_tcp("", 0, timeout=5, model=None, app="t")
        assert result["status"] == "skipped"

    def test_tcp_success(self) -> None:
        with patch("subprocess.run", return_value=_proc(returncode=0)):
            result = WorkloadEndpointTool._probe_tcp("h", 8080, timeout=5, model=None, app="t")
        assert result["status"] == "pass"
        assert result["notes"] == "Port open"

    def test_tcp_failure_records_stderr(self) -> None:
        with patch(
            "subprocess.run",
            return_value=_proc(returncode=1, stderr="closed"),
        ):
            result = WorkloadEndpointTool._probe_tcp("h", 8080, timeout=5, model=None, app="t")
        assert result["status"] == "failed"
        assert "closed" in result["notes"]

    def test_tcp_timeout_records_error(self) -> None:
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="ssh", timeout=1)):
            result = WorkloadEndpointTool._probe_tcp("h", 8080, timeout=5, model=None, app="t")
        assert result["status"] == "failed"
        assert "TCP probe error" in result["notes"]

    def test_tcp_threads_model_arg(self) -> None:
        captured: list[list[str]] = []

        def _mock_run(cmd: list[str], **_kwargs: Any) -> MagicMock:
            captured.append(cmd)
            return _proc(returncode=0)

        with patch("subprocess.run", side_effect=_mock_run):
            WorkloadEndpointTool._probe_tcp("h", 8080, timeout=5, model="dev", app="t")
        assert any("--model" in cmd and "dev" in cmd for cmd in captured)


# ---------------------------------------------------------------------------
# ConfigVariationTool
# ---------------------------------------------------------------------------


class TestConfigVariationBranches:
    """ConfigVariationTool branches that require live juju mocks."""

    @pytest.mark.asyncio
    async def test_no_juju_short_circuits(self) -> None:
        with patch("shutil.which", return_value=None):
            result = await ConfigVariationTool().execute(app="t")
        assert result.success is False

    @pytest.mark.asyncio
    async def test_set_failure_is_recorded(self, tmp_path: pathlib.Path) -> None:
        (tmp_path / "charmcraft.yaml").write_text(
            "name: t\nconfig:\n  options:\n    port:\n      type: int\n      default: 8080\n"
        )
        with (
            patch("shutil.which", return_value="/usr/bin/juju"),
            patch(
                "cantrip.agent.tools.acceptance.juju_subprocess.run_juju",
                return_value=_proc(returncode=1, stderr="bad value"),
            ),
        ):
            result = await ConfigVariationTool().execute(app="t", path=str(tmp_path))
        assert result.success is False
        assert any("Set failed" in r["notes"] for r in result.data["results"])

    @pytest.mark.asyncio
    async def test_set_timeout_is_recorded(self, tmp_path: pathlib.Path) -> None:
        (tmp_path / "charmcraft.yaml").write_text(
            "name: t\nconfig:\n  options:\n    port:\n      type: int\n      default: 8080\n"
        )
        with (
            patch("shutil.which", return_value="/usr/bin/juju"),
            patch(
                "cantrip.agent.tools.acceptance.juju_subprocess.run_juju",
                side_effect=subprocess.TimeoutExpired(cmd="juju", timeout=1),
            ),
        ):
            result = await ConfigVariationTool().execute(app="t", path=str(tmp_path))
        assert any("timed out" in r["notes"] for r in result.data["results"])

    @pytest.mark.asyncio
    async def test_settle_succeeds_then_resets(self, tmp_path: pathlib.Path) -> None:
        (tmp_path / "charmcraft.yaml").write_text(
            "name: t\nconfig:\n  options:\n    port:\n      type: int\n      default: 8080\n"
        )
        with (
            patch("shutil.which", return_value="/usr/bin/juju"),
            patch(
                "cantrip.agent.tools.acceptance.juju_subprocess.run_juju",
                return_value=_proc(returncode=0),
            ),
            patch(
                "cantrip.agent.tools.acceptance.juju_subprocess.wait_for_app",
                return_value=True,
            ),
        ):
            result = await ConfigVariationTool().execute(app="t", path=str(tmp_path))
        assert result.success is True
        assert all(r["settled_ok"] for r in result.data["results"])

    @pytest.mark.asyncio
    async def test_reset_timeout_is_swallowed(self, tmp_path: pathlib.Path) -> None:
        # Reset path: the second wait_for_app raises TimeoutExpired but
        # the helper swallows it via the bare ``except``.  Coverage line.
        (tmp_path / "charmcraft.yaml").write_text(
            "name: t\nconfig:\n  options:\n    port:\n      type: int\n      default: 8080\n"
        )

        call_count = {"n": 0}

        def _mock_run(*_args: Any, **_kwargs: Any) -> MagicMock:
            call_count["n"] += 1
            # Second invocation is the reset; raise to hit the bare-except.
            if call_count["n"] >= 2:
                raise subprocess.TimeoutExpired(cmd="juju", timeout=1)
            return _proc(returncode=0)

        with (
            patch("shutil.which", return_value="/usr/bin/juju"),
            patch(
                "cantrip.agent.tools.acceptance.juju_subprocess.run_juju",
                side_effect=_mock_run,
            ),
            patch(
                "cantrip.agent.tools.acceptance.juju_subprocess.wait_for_app",
                return_value=True,
            ),
        ):
            result = await ConfigVariationTool().execute(app="t", path=str(tmp_path))
        # Set-then-settle fired before the reset blew up; the result stands.
        assert result.success is True

    @pytest.mark.asyncio
    async def test_skip_options_arg(self, tmp_path: pathlib.Path) -> None:
        (tmp_path / "charmcraft.yaml").write_text(
            "name: t\nconfig:\n  options:\n    port:\n      type: int\n      default: 8080\n"
        )
        with patch("shutil.which", return_value="/usr/bin/juju"):
            result = await ConfigVariationTool().execute(
                app="t",
                path=str(tmp_path),
                skip_options=["port"],
            )
        assert result.data["options_tested"] == 0

    @pytest.mark.asyncio
    async def test_unknown_type_option_is_skipped(self, tmp_path: pathlib.Path) -> None:
        # ``_generate_test_value`` returns None for unknown types — the
        # tool must skip rather than crash.
        (tmp_path / "charmcraft.yaml").write_text(
            "name: t\nconfig:\n  options:\n    weird:\n      type: customtype\n"
        )
        with patch("shutil.which", return_value="/usr/bin/juju"):
            result = await ConfigVariationTool().execute(app="t", path=str(tmp_path))
        assert result.data["options_tested"] == 0

    @pytest.mark.asyncio
    async def test_non_dict_option_spec_is_skipped(self, tmp_path: pathlib.Path) -> None:
        # ``options:\n  bare: yes`` parses to ``{"bare": True}`` — the
        # ``not isinstance(opt_spec, dict)`` branch.
        (tmp_path / "charmcraft.yaml").write_text(
            "name: t\nconfig:\n  options:\n    bare: ok-string\n"
        )
        with patch("shutil.which", return_value="/usr/bin/juju"):
            result = await ConfigVariationTool().execute(app="t", path=str(tmp_path))
        assert result.data["options_tested"] == 0


# ---------------------------------------------------------------------------
# ConfigUnderLoadTool — non-200 + error + model
# ---------------------------------------------------------------------------


class TestConfigUnderLoadBranches:
    """ConfigUnderLoadTool branches the existing all-pass test skips."""

    @pytest.mark.asyncio
    async def test_some_probes_fail_marks_overall_failure(self) -> None:
        # Curl reports 503 — non-OK path.
        def _mock_run(cmd: list[str], **_kwargs: Any) -> MagicMock:
            if cmd[0] == "curl":
                return _proc(returncode=0, stdout="503")
            return _proc(returncode=0)

        with (
            patch("shutil.which", return_value="/usr/bin/juju"),
            patch("subprocess.run", side_effect=_mock_run),
        ):
            result = await ConfigUnderLoadTool().execute(
                app="t",
                config_key="port",
                config_value="9090",
                health_url="http://h:8080/health",
                probe_count=2,
                probe_interval=0.001,
            )
        assert result.success is False
        assert result.data["errors"] >= 1

    @pytest.mark.asyncio
    async def test_curl_exception_recorded_as_failure(self) -> None:
        def _mock_run(cmd: list[str], **_kwargs: Any) -> MagicMock:
            if cmd[0] == "curl":
                raise subprocess.TimeoutExpired(cmd="curl", timeout=1)
            return _proc(returncode=0)

        with (
            patch("shutil.which", return_value="/usr/bin/juju"),
            patch("subprocess.run", side_effect=_mock_run),
        ):
            result = await ConfigUnderLoadTool().execute(
                app="t",
                config_key="port",
                config_value="9090",
                health_url="http://h:8080/health",
                probe_count=2,
                probe_interval=0.001,
            )
        assert result.success is False
        # Each errored probe contributes status 0.
        assert all(p["status"] == 0 for p in result.data["probes"])

    @pytest.mark.asyncio
    async def test_model_arg_is_threaded_into_juju_calls(self) -> None:
        captured: list[list[str]] = []

        def _mock_run(cmd: list[str], **_kwargs: Any) -> MagicMock:
            captured.append(cmd)
            if cmd[0] == "curl":
                return _proc(returncode=0, stdout="200")
            return _proc(returncode=0)

        with (
            patch("shutil.which", return_value="/usr/bin/juju"),
            patch("subprocess.run", side_effect=_mock_run),
        ):
            await ConfigUnderLoadTool().execute(
                app="t",
                config_key="port",
                config_value="9090",
                health_url="http://h:8080/health",
                model="dev",
                probe_count=1,
                probe_interval=0.001,
            )
        # Both the apply-config and reset commands carry --model dev.
        juju_calls = [c for c in captured if c[0] == "juju"]
        assert all("--model" in c and "dev" in c for c in juju_calls)


# ---------------------------------------------------------------------------
# AcceptanceReportTool — branches the base suite skips
# ---------------------------------------------------------------------------


class TestAcceptanceReportBranches:
    """AcceptanceReportTool failure / lifecycle branches."""

    @pytest.mark.asyncio
    async def test_non_existent_directory(self, tmp_path: pathlib.Path) -> None:
        result = await AcceptanceReportTool().execute(
            app="myapp",
            path=str(tmp_path / "nope"),
        )
        assert result.success is False
        assert "Directory not found" in (result.error or "")

    @pytest.mark.asyncio
    async def test_relations_and_endpoints_sections(self, tmp_path: pathlib.Path) -> None:
        result = await AcceptanceReportTool().execute(
            app="myapp",
            path=str(tmp_path),
            relations="## Relations\nAll up.",
            endpoints="## Endpoints\nAll responsive.",
        )
        assert result.success is True
        body = (tmp_path / "ACCEPTANCE.md").read_text()
        assert "Relations" in body
        assert "Endpoints" in body
        assert "relations tested" in result.data["sections"]
        assert "endpoints probed" in result.data["sections"]

    @pytest.mark.asyncio
    async def test_lifecycle_section_is_included(self, tmp_path: pathlib.Path) -> None:
        result = await AcceptanceReportTool().execute(
            app="myapp",
            path=str(tmp_path),
            lifecycle="## Lifecycle\nAll passed.",
        )
        assert result.success is True
        body = (tmp_path / "ACCEPTANCE.md").read_text()
        assert "Lifecycle" in body
        assert "lifecycle" in result.data["sections"][0]
