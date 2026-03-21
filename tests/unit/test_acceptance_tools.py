"""Tests for acceptance testing tools."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from cantrip.agent.tools.acceptance import (
    _DESTRUCTIVE_PATTERNS,
    _INTERFACE_PARTNERS,
    AcceptanceReportTool,
    ActionExerciserTool,
    ConfigVariationTool,
    RelationSmokeTool,
    WorkloadEndpointTool,
    _generate_action_params,
    _generate_test_value,
)

# ---------------------------------------------------------------------------
# ActionExerciserTool
# ---------------------------------------------------------------------------


class TestActionExerciserTool:
    """Tests for ActionExerciserTool basics."""

    def test_tool_name(self) -> None:
        tool = ActionExerciserTool()
        assert tool.name == "action_exerciser"

    def test_parameters_schema(self) -> None:
        tool = ActionExerciserTool()
        params = tool.parameters
        props = params["properties"]
        assert "app" in props
        assert "path" in props
        assert "model" in props
        assert "skip_destructive" in props
        assert "timeout" in props
        assert params["required"] == ["app"]

    @pytest.mark.asyncio
    async def test_missing_app(self) -> None:
        tool = ActionExerciserTool()
        result = await tool.execute(app="")
        assert not result.success
        assert "app parameter is required" in (result.error or "")

    @pytest.mark.asyncio
    async def test_no_juju(self) -> None:
        tool = ActionExerciserTool()
        with patch("shutil.which", return_value=None):
            result = await tool.execute(app="myapp")
        assert not result.success
        assert "juju CLI not found" in (result.error or "")

    @pytest.mark.asyncio
    async def test_no_actions(self, tmp_path: Path) -> None:
        """Charm with no actions produces a clean report."""
        charmcraft = tmp_path / "charmcraft.yaml"
        charmcraft.write_text("name: test-charm\n")

        tool = ActionExerciserTool()
        with patch("shutil.which", return_value="/usr/bin/juju"):
            result = await tool.execute(app="test-charm", path=str(tmp_path))
        assert result.success
        assert result.data["actions_tested"] == 0

    @pytest.mark.asyncio
    async def test_destructive_actions_skipped(self, tmp_path: Path) -> None:
        """Destructive actions are skipped by default."""
        charmcraft = tmp_path / "charmcraft.yaml"
        charmcraft.write_text(
            "name: test-charm\n"
            "actions:\n"
            "  delete-data:\n"
            "    description: Dangerous\n"
            "  get-status:\n"
            "    description: Safe\n"
        )

        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = '{"status": "completed"}'
        mock_proc.stderr = ""

        tool = ActionExerciserTool()
        with (
            patch("shutil.which", return_value="/usr/bin/juju"),
            patch("subprocess.run", return_value=mock_proc),
        ):
            result = await tool.execute(app="test-charm", path=str(tmp_path))

        assert result.data["actions_skipped"] == 1
        assert result.data["actions_tested"] == 1

    @pytest.mark.asyncio
    async def test_skip_destructive_false(self, tmp_path: Path) -> None:
        """When skip_destructive=False, all actions run."""
        charmcraft = tmp_path / "charmcraft.yaml"
        charmcraft.write_text(
            "name: test-charm\n"
            "actions:\n"
            "  delete-data:\n"
            "    description: Dangerous\n"
            "  get-status:\n"
            "    description: Safe\n"
        )

        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = "{}"
        mock_proc.stderr = ""

        tool = ActionExerciserTool()
        with (
            patch("shutil.which", return_value="/usr/bin/juju"),
            patch("subprocess.run", return_value=mock_proc),
        ):
            result = await tool.execute(
                app="test-charm",
                path=str(tmp_path),
                skip_destructive=False,
            )

        assert result.data["actions_skipped"] == 0
        assert result.data["actions_tested"] == 2


# ---------------------------------------------------------------------------
# Destructive pattern matching
# ---------------------------------------------------------------------------


class TestDestructivePatterns:
    """Tests for the destructive action name regex."""

    @pytest.mark.parametrize(
        "name",
        [
            "delete-data",
            "destroy-cluster",
            "reset-config",
            "purge-logs",
            "wipe-storage",
            "remove-user",
            "drop-table",
            "erase-history",
            "nuke-everything",
        ],
    )
    def test_destructive_names_match(self, name: str) -> None:
        assert _DESTRUCTIVE_PATTERNS.match(name)

    @pytest.mark.parametrize(
        "name",
        ["get-status", "create-backup", "list-users", "health-check", "restart"],
    )
    def test_safe_names_do_not_match(self, name: str) -> None:
        assert not _DESTRUCTIVE_PATTERNS.match(name)


# ---------------------------------------------------------------------------
# Action parameter generation
# ---------------------------------------------------------------------------


class TestGenerateActionParams:
    """Tests for _generate_action_params helper."""

    def test_empty_spec(self) -> None:
        assert _generate_action_params({}) == {}

    def test_default_values(self) -> None:
        spec = {"params": {"name": {"type": "string", "default": "hello"}}}
        assert _generate_action_params(spec) == {"name": "hello"}

    def test_boolean_type(self) -> None:
        spec = {"params": {"force": {"type": "boolean"}}}
        assert _generate_action_params(spec) == {"force": "true"}

    def test_integer_with_minimum(self) -> None:
        spec = {"params": {"count": {"type": "integer", "minimum": 5}}}
        assert _generate_action_params(spec) == {"count": "5"}

    def test_string_with_enum(self) -> None:
        spec = {"params": {"level": {"type": "string", "enum": ["low", "high"]}}}
        assert _generate_action_params(spec) == {"level": "low"}

    def test_string_without_enum(self) -> None:
        spec = {"params": {"name": {"type": "string"}}}
        assert _generate_action_params(spec) == {"name": "test"}


# ---------------------------------------------------------------------------
# Config test value generation
# ---------------------------------------------------------------------------


class TestGenerateTestValue:
    """Tests for _generate_test_value helper."""

    def test_boolean_toggle_true(self) -> None:
        assert _generate_test_value("boolean", True) == "false"

    def test_boolean_toggle_false(self) -> None:
        assert _generate_test_value("boolean", False) == "true"

    def test_boolean_toggle_none(self) -> None:
        assert _generate_test_value("boolean", None) == "true"

    def test_int_increment(self) -> None:
        assert _generate_test_value("int", 8080) == "8081"

    def test_int_from_none(self) -> None:
        assert _generate_test_value("int", None) == "1"

    def test_float_increment(self) -> None:
        assert _generate_test_value("float", 1.0) == "1.5"

    def test_string_with_default(self) -> None:
        assert _generate_test_value("string", "foo") == "foo-test"

    def test_string_empty(self) -> None:
        assert _generate_test_value("string", "") == "test-value"

    def test_unknown_type(self) -> None:
        assert _generate_test_value("unknown", None) is None


# ---------------------------------------------------------------------------
# RelationSmokeTool
# ---------------------------------------------------------------------------


class TestRelationSmokeTool:
    """Tests for RelationSmokeTool basics."""

    def test_tool_name(self) -> None:
        tool = RelationSmokeTool()
        assert tool.name == "relation_smoke_test"

    def test_parameters_schema(self) -> None:
        tool = RelationSmokeTool()
        params = tool.parameters
        props = params["properties"]
        assert "app" in props
        assert "path" in props
        assert "skip_endpoints" in props
        assert params["required"] == ["app"]

    @pytest.mark.asyncio
    async def test_missing_app(self) -> None:
        tool = RelationSmokeTool()
        result = await tool.execute(app="")
        assert not result.success

    @pytest.mark.asyncio
    async def test_no_relations(self, tmp_path: Path) -> None:
        """Charm with no relations produces a clean report."""
        charmcraft = tmp_path / "charmcraft.yaml"
        charmcraft.write_text("name: test-charm\n")

        tool = RelationSmokeTool()
        with patch("shutil.which", return_value="/usr/bin/juju"):
            result = await tool.execute(app="test-charm", path=str(tmp_path))
        assert result.success
        assert result.data["endpoints_tested"] == 0

    @pytest.mark.asyncio
    async def test_peer_relations_skipped(self, tmp_path: Path) -> None:
        """Peer relations should be skipped (tested via scaling instead)."""
        charmcraft = tmp_path / "charmcraft.yaml"
        charmcraft.write_text("name: test-charm\npeers:\n  cluster:\n    interface: cluster\n")

        tool = RelationSmokeTool()
        with patch("shutil.which", return_value="/usr/bin/juju"):
            result = await tool.execute(app="test-charm", path=str(tmp_path))
        assert result.success
        # Peer was recorded but not "tested" (skipped).
        assert result.data["endpoints_tested"] == 0


# ---------------------------------------------------------------------------
# Interface partner mapping
# ---------------------------------------------------------------------------


class TestInterfacePartners:
    """Tests for the _INTERFACE_PARTNERS mapping."""

    def test_common_interfaces_covered(self) -> None:
        for interface in (
            "mysql_client",
            "pgsql",
            "ingress",
            "grafana-dashboard",
            "metrics-endpoint",
            "logging",
            "tracing",
        ):
            assert interface in _INTERFACE_PARTNERS, f"{interface} missing"

    def test_partners_are_strings(self) -> None:
        for interface, partner in _INTERFACE_PARTNERS.items():
            assert isinstance(partner, str), f"{interface} partner is not a string"


# ---------------------------------------------------------------------------
# WorkloadEndpointTool
# ---------------------------------------------------------------------------


class TestWorkloadEndpointTool:
    """Tests for WorkloadEndpointTool basics."""

    def test_tool_name(self) -> None:
        tool = WorkloadEndpointTool()
        assert tool.name == "workload_endpoint_test"

    def test_parameters_schema(self) -> None:
        tool = WorkloadEndpointTool()
        params = tool.parameters
        props = params["properties"]
        assert "app" in props
        assert "endpoints" in props
        assert "timeout" in props
        assert params["required"] == ["app"]

    @pytest.mark.asyncio
    async def test_missing_app(self) -> None:
        tool = WorkloadEndpointTool()
        result = await tool.execute(app="")
        assert not result.success

    @pytest.mark.asyncio
    async def test_no_endpoints(self, tmp_path: Path) -> None:
        """Charm with no container ports produces a clean report."""
        charmcraft = tmp_path / "charmcraft.yaml"
        charmcraft.write_text("name: test-charm\n")

        mock_status = MagicMock()
        mock_status.returncode = 0
        mock_status.stdout = '{"applications": {}}'

        tool = WorkloadEndpointTool()
        with (
            patch("shutil.which", return_value="/usr/bin/juju"),
            patch(
                "cantrip.agent.tools.acceptance._run_juju",
                return_value=mock_status,
            ),
        ):
            result = await tool.execute(app="test-charm", path=str(tmp_path))
        assert result.success
        assert result.data["endpoints_tested"] == 0

    def test_discover_endpoints_from_metadata(self, tmp_path: Path) -> None:
        """Container ports in charmcraft.yaml are discovered."""
        charmcraft = tmp_path / "charmcraft.yaml"
        charmcraft.write_text(
            "name: test-charm\ncontainers:\n  app:\n    ports:\n      - target: 8080\n"
        )
        probes = WorkloadEndpointTool._discover_endpoints(str(tmp_path), "10.0.0.1")
        # Should find port 8080 plus health paths.
        ports = [p.get("port") for p in probes if p.get("port")]
        assert 8080 in ports


# ---------------------------------------------------------------------------
# ConfigVariationTool
# ---------------------------------------------------------------------------


class TestConfigVariationTool:
    """Tests for ConfigVariationTool basics."""

    def test_tool_name(self) -> None:
        tool = ConfigVariationTool()
        assert tool.name == "config_variation_test"

    def test_parameters_schema(self) -> None:
        tool = ConfigVariationTool()
        params = tool.parameters
        props = params["properties"]
        assert "app" in props
        assert "skip_options" in props
        assert params["required"] == ["app"]

    @pytest.mark.asyncio
    async def test_missing_app(self) -> None:
        tool = ConfigVariationTool()
        result = await tool.execute(app="")
        assert not result.success

    @pytest.mark.asyncio
    async def test_no_config(self, tmp_path: Path) -> None:
        """Charm with no config produces a clean report."""
        charmcraft = tmp_path / "charmcraft.yaml"
        charmcraft.write_text("name: test-charm\n")

        tool = ConfigVariationTool()
        with patch("shutil.which", return_value="/usr/bin/juju"):
            result = await tool.execute(app="test-charm", path=str(tmp_path))
        assert result.success
        assert result.data["options_tested"] == 0

    @pytest.mark.asyncio
    async def test_path_options_skipped(self, tmp_path: Path) -> None:
        """Config options with 'path' in the name should be skipped."""
        charmcraft = tmp_path / "charmcraft.yaml"
        charmcraft.write_text(
            "name: test-charm\n"
            "config:\n"
            "  options:\n"
            "    data-path:\n"
            "      type: string\n"
            "      default: /data\n"
            "    port:\n"
            "      type: int\n"
            "      default: 8080\n"
        )

        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = ""
        mock_proc.stderr = ""

        tool = ConfigVariationTool()
        with (
            patch("shutil.which", return_value="/usr/bin/juju"),
            patch(
                "cantrip.agent.tools.acceptance._run_juju",
                return_value=mock_proc,
            ),
            patch(
                "cantrip.agent.tools.acceptance._wait_for_app",
                return_value=True,
            ),
        ):
            result = await tool.execute(app="test-charm", path=str(tmp_path))

        # data-path should be skipped, port should be tested.
        assert result.data["options_tested"] == 1


# ---------------------------------------------------------------------------
# AcceptanceReportTool
# ---------------------------------------------------------------------------


class TestAcceptanceReportTool:
    """Tests for AcceptanceReportTool basics."""

    def test_tool_name(self) -> None:
        tool = AcceptanceReportTool()
        assert tool.name == "acceptance_report"

    def test_parameters_schema(self) -> None:
        tool = AcceptanceReportTool()
        params = tool.parameters
        props = params["properties"]
        assert "app" in props
        assert "actions" in props
        assert "relations" in props
        assert "endpoints" in props
        assert "config" in props
        assert "lifecycle" in props
        assert params["required"] == ["app"]

    @pytest.mark.asyncio
    async def test_missing_app(self) -> None:
        tool = AcceptanceReportTool()
        result = await tool.execute(app="")
        assert not result.success

    @pytest.mark.asyncio
    async def test_no_sections(self, tmp_path: Path) -> None:
        """No sections provided should fail."""
        tool = AcceptanceReportTool()
        result = await tool.execute(app="myapp", path=str(tmp_path))
        assert not result.success
        assert "No acceptance test results" in (result.error or "")

    @pytest.mark.asyncio
    async def test_writes_acceptance_md(self, tmp_path: Path) -> None:
        """Report tool writes ACCEPTANCE.md to the charm directory."""
        tool = AcceptanceReportTool()
        result = await tool.execute(
            app="myapp",
            path=str(tmp_path),
            actions="## Actions\nAll passed.",
            config="## Config\nAll settled.",
        )
        assert result.success
        assert result.data["section_count"] == 2
        acceptance_file = tmp_path / "ACCEPTANCE.md"
        assert acceptance_file.exists()
        content = acceptance_file.read_text()
        assert "myapp" in content
        assert "Actions" in content
        assert "Config" in content


# ---------------------------------------------------------------------------
# Autodeploy chaining
# ---------------------------------------------------------------------------


class TestAcceptanceAutodeploy:
    """Tests for acceptance test chaining in autodeploy."""

    def test_test_task_chains_to_acceptance(self) -> None:
        from cantrip.agent.autodeploy import tasks_after_test
        from cantrip.agent.queue import AgentTask, TaskCategory, TaskStatus

        task = AgentTask(
            id="test-1",
            title="Run integration tests",
            category=TaskCategory.TEST,
        )
        task.status = TaskStatus.DONE

        follow_ups = tasks_after_test(task)
        assert len(follow_ups) == 1
        assert follow_ups[0].title.startswith("Acceptance test:")
        assert follow_ups[0].category == TaskCategory.TEST

    def test_acceptance_chains_to_demo(self) -> None:
        from cantrip.agent.autodeploy import tasks_after_acceptance
        from cantrip.agent.queue import AgentTask, TaskCategory, TaskStatus

        task = AgentTask(
            id="accept-1",
            title="Acceptance test: put the charm through its paces",
            category=TaskCategory.TEST,
        )
        task.status = TaskStatus.DONE

        follow_ups = tasks_after_acceptance(task)
        assert len(follow_ups) == 1
        assert "demo" in follow_ups[0].title.lower()
        assert follow_ups[0].category == TaskCategory.BUILD

    def test_acceptance_does_not_chain_to_itself(self) -> None:
        from cantrip.agent.autodeploy import tasks_after_test
        from cantrip.agent.queue import AgentTask, TaskCategory, TaskStatus

        task = AgentTask(
            id="accept-1",
            title="Acceptance test: put the charm through its paces",
            category=TaskCategory.TEST,
        )
        task.status = TaskStatus.DONE

        follow_ups = tasks_after_test(task)
        assert len(follow_ups) == 0

    def test_demo_does_not_chain_to_acceptance(self) -> None:
        from cantrip.agent.autodeploy import tasks_after_test
        from cantrip.agent.queue import AgentTask, TaskCategory, TaskStatus

        task = AgentTask(
            id="demo-test-1",
            title="Generate demo validation",
            category=TaskCategory.TEST,
        )
        task.status = TaskStatus.DONE

        follow_ups = tasks_after_test(task)
        assert len(follow_ups) == 0

    def test_non_acceptance_does_not_trigger_demo(self) -> None:
        from cantrip.agent.autodeploy import tasks_after_acceptance
        from cantrip.agent.queue import AgentTask, TaskCategory, TaskStatus

        task = AgentTask(
            id="test-1",
            title="Run integration tests",
            category=TaskCategory.TEST,
        )
        task.status = TaskStatus.DONE

        follow_ups = tasks_after_acceptance(task)
        assert len(follow_ups) == 0
