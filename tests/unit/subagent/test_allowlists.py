"""Subagent tests: allowlists."""

from cantrip.agent.queue import TaskCategory
from cantrip.agent.subagent import (
    _CATEGORY_TOOLS,
    _filter_tools,
    _select_provider,
)
from tests.conftest import FakeProvider
from tests.unit.subagent.conftest import _make_tool

# ===================================================================
# TestResearchToolAllowlist
# ===================================================================


class TestResearchToolAllowlist:
    """Tests for write_file being in the RESEARCH tool allowlist."""

    def test_write_file_in_research_tools(self) -> None:
        tools = [_make_tool("write_file"), _make_tool("read_file")]
        filtered = _filter_tools(tools, TaskCategory.RESEARCH)
        names = {t.name for t in filtered}
        assert "write_file" in names


# ===================================================================
# TestOperationalDiscoveryUsePrimaryModel
# ===================================================================


class TestOperationalDiscoveryUsePrimaryModel:
    """Tests for routing operational-discovery tasks to the primary model."""

    def test_operational_discovery_uses_primary(self) -> None:
        primary = FakeProvider()
        light = FakeProvider()
        result = _select_provider(
            TaskCategory.RESEARCH, primary, light, task_title="operational-discovery"
        )
        assert result is primary

    def test_synthesise_uses_primary(self) -> None:
        primary = FakeProvider()
        light = FakeProvider()
        result = _select_provider(
            TaskCategory.RESEARCH, primary, light, task_title="Synthesise design proposal"
        )
        assert result is primary

    def test_regular_research_uses_light(self) -> None:
        primary = FakeProvider()
        light = FakeProvider()
        result = _select_provider(
            TaskCategory.RESEARCH, primary, light, task_title="Research the workload"
        )
        assert result is light

    def test_no_light_provider_uses_primary(self) -> None:
        primary = FakeProvider()
        result = _select_provider(
            TaskCategory.RESEARCH, primary, None, task_title="operational-discovery"
        )
        assert result is primary


# ===================================================================
# TestCharmAuditToolAllowlists
# ===================================================================


class TestCharmAuditToolAllowlists:
    """Tests for charm_audit tool registration in category allowlists."""

    def test_charm_audit_in_research_tools(self) -> None:
        """charm_audit is available to RESEARCH subagents for auditing."""
        assert "charm_audit" in _CATEGORY_TOOLS[TaskCategory.RESEARCH]

    def test_charm_audit_in_build_tools(self) -> None:
        """charm_audit is available to BUILD subagents for re-checking after fixes."""
        assert "charm_audit" in _CATEGORY_TOOLS[TaskCategory.BUILD]


# ===================================================================
# TestBenchmarkAndFuzzToolAllowlists
# ===================================================================


class TestAdvancedTestingToolAllowlists:
    """Tests for advanced testing tool registration in category allowlists."""

    def test_hook_benchmark_in_test_tools(self) -> None:
        assert "hook_benchmark" in _CATEGORY_TOOLS[TaskCategory.TEST]

    def test_fuzz_charm_in_test_tools(self) -> None:
        assert "fuzz_charm" in _CATEGORY_TOOLS[TaskCategory.TEST]

    def test_fuzz_charm_in_build_tools(self) -> None:
        assert "fuzz_charm" in _CATEGORY_TOOLS[TaskCategory.BUILD]

    def test_test_report_in_test_tools(self) -> None:
        assert "test_report" in _CATEGORY_TOOLS[TaskCategory.TEST]

    def test_chaos_test_in_test_tools(self) -> None:
        assert "chaos_test" in _CATEGORY_TOOLS[TaskCategory.TEST]

    def test_scaling_test_in_test_tools(self) -> None:
        assert "scaling_test" in _CATEGORY_TOOLS[TaskCategory.TEST]

    def test_upgrade_test_in_test_tools(self) -> None:
        assert "upgrade_test" in _CATEGORY_TOOLS[TaskCategory.TEST]
