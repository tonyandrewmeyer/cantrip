"""Agent tools."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from cantrip.agent.tools.base import Tool, ToolResult, execute_tool, tool_to_schema


def build_tools(
    *,
    base_path: Path | None = None,
    skills_index: SkillsIndex | None = None,
    virtual_store: VirtualFileStore | None = None,
    provider: Any = None,
    state: Any = None,
    queue: Any = None,
    memory_manager: MemoryManager | None = None,
    mcp_registry: MCPRegistry | None = None,
) -> list[Tool]:
    """Build all agent tool instances.

    Centralises tool construction so callers do not need to import
    every tool class individually.  Parameters with dependencies
    (skills, virtual store, etc.) are passed in explicitly.

    Tool modules are imported lazily inside this function — importing
    all ~100 tool classes at package-import time previously added ~1.6s
    to every TUI / CLI startup, even for commands that never build an
    agent.
    """
    # Late imports: keep ``cantrip.agent.tools`` itself cheap to import.
    from cantrip.agent.tools.acceptance import (
        AcceptanceReportTool,
        ActionExerciserTool,
        ConfigUnderLoadTool,
        ConfigVariationTool,
        RelationSmokeTool,
        WorkloadEndpointTool,
    )
    from cantrip.agent.tools.audit import CharmAuditTool
    from cantrip.agent.tools.benchmark import HookBenchmarkTool
    from cantrip.agent.tools.chaos import ChaosTestTool
    from cantrip.agent.tools.charm import (
        AnalyseFrameworkTool,
        CharmcraftFetchLibsTool,
        CharmcraftInitTool,
        CharmcraftPackTool,
        CharmValidateTool,
        GenerateTerraformTool,
        QuickPackTool,
        ValidateTerraformTool,
    )
    from cantrip.agent.tools.charmhub import CharmhubInfoTool, CharmhubSearchTool
    from cantrip.agent.tools.charmlint_tool import CharmlintTool
    from cantrip.agent.tools.environment import ConciergePrepareTool, ConciergeStatusTool
    from cantrip.agent.tools.files import (
        EditFileTool,
        ListDirectoryTool,
        ReadFileTool,
        WriteFileTool,
    )
    from cantrip.agent.tools.fuzz import FuzzTestTool
    from cantrip.agent.tools.git import (
        GitAddTool,
        GitBranchTool,
        GitCheckoutTool,
        GitCloneTool,
        GitCommitTool,
        GitDiffTool,
        GitInitTool,
        GitLogTool,
        GitPushTool,
        GitStashTool,
        GitStatusTool,
    )
    from cantrip.agent.tools.github import (
        GhIssueListTool,
        GhPrCreateTool,
        GhPrListTool,
        GhPrViewTool,
        GhRepoBootstrapTool,
        GhRepoCreateTool,
    )
    from cantrip.agent.tools.glob import GlobTool
    from cantrip.agent.tools.grep import GrepTool
    from cantrip.agent.tools.inference import ListInferenceSnapsTool
    from cantrip.agent.tools.juju import (
        BundleDeployTool,
        CharmSyncTool,
        JujuAddModelTool,
        JujuConfigTool,
        JujuConsumeTool,
        JujuDeployTool,
        JujuDestroyModelTool,
        JujuDispatchTool,
        JujuGetAppConfigTool,
        JujuListOffersTool,
        JujuListSecretsTool,
        JujuOfferTool,
        JujuReadRelationDataTool,
        JujuRefreshTool,
        JujuRelateTool,
        JujuRemoveApplicationTool,
        JujuRunActionTool,
        JujuShowSecretTool,
        JujuShowUnitTool,
        JujuSSHTool,
        JujuStatusTool,
        JujuTrustTool,
        JujuWaitTool,
    )
    from cantrip.agent.tools.loadtest import GenerateLoadTestTool
    from cantrip.agent.tools.mcp_tool import MCPTool
    from cantrip.agent.tools.memory import build_memory_tools
    from cantrip.agent.tools.multi_edit import MultiEditTool
    from cantrip.agent.tools.observability import (
        GrafanaScreenshotTool,
        JujuDebugLogTool,
        JujuStreamLogsTool,
        LokiQueryTool,
        TempoQueryTool,
        TempoWaterfallTool,
    )
    from cantrip.agent.tools.oci_registry import (
        RegistryImageInfoTool,
        RegistrySearchTool,
    )
    from cantrip.agent.tools.operational_readiness import OperationalReadinessTool
    from cantrip.agent.tools.planning import PlanTasksTool
    from cantrip.agent.tools.pr_review import PrReviewReplyTool, PrReviewTool
    from cantrip.agent.tools.publishing import (
        CharmcraftReleaseTool,
        CharmcraftUploadTool,
        GenerateDiagramTool,
        GenerateDocsTool,
        GenerateIconTool,
        GenerateReadmeTool,
    )
    from cantrip.agent.tools.report import TestReportTool
    from cantrip.agent.tools.rockcraft import (
        RockcraftInitTool,
        RockcraftPackTool,
        SkopeoRegistryPushTool,
    )
    from cantrip.agent.tools.rodney import RodneyTool
    from cantrip.agent.tools.run_command import RunCommandTool
    from cantrip.agent.tools.scaling import ScalingTestTool
    from cantrip.agent.tools.showboat import ShowboatTool
    from cantrip.agent.tools.skills import LoadSkillTool
    from cantrip.agent.tools.task_management import ManageTasksTool
    from cantrip.agent.tools.testing import GenerateTestsTool, RunCharmTestsTool
    from cantrip.agent.tools.upgrade import UpgradeTestTool
    from cantrip.agent.tools.virtual_files import VirtualFileReadTool, VirtualFileSearchTool
    from cantrip.agent.tools.web import WebFetchTool
    from cantrip.agent.tools.web_search import WebSearchTool
    from cantrip.agent.tools.workspace import WorkspaceInfoTool

    tools: list[Tool] = [
        # File operations
        ReadFileTool(base_path=base_path),
        WriteFileTool(base_path=base_path),
        ListDirectoryTool(base_path=base_path),
        EditFileTool(base_path=base_path),
        GrepTool(base_path=base_path),
        GlobTool(base_path=base_path),
        MultiEditTool(base_path=base_path),
        # Audit & lint
        CharmAuditTool(),
        CharmlintTool(),
        OperationalReadinessTool(),
        # Charm operations
        CharmcraftInitTool(),
        CharmcraftPackTool(),
        QuickPackTool(),
        CharmValidateTool(),
        CharmcraftFetchLibsTool(),
        AnalyseFrameworkTool(),
        # Terraform
        GenerateTerraformTool(),
        ValidateTerraformTool(),
        # Publishing
        CharmcraftUploadTool(),
        CharmcraftReleaseTool(),
        GenerateReadmeTool(),
        GenerateIconTool(),
        GenerateDocsTool(),
        GenerateDiagramTool(),
        GenerateLoadTestTool(),
        # Demo
        ShowboatTool(),
        RodneyTool(),
        # Web
        WebFetchTool(),
        WebSearchTool(),
        # Charmhub
        CharmhubSearchTool(),
        CharmhubInfoTool(),
        # Registry
        RegistrySearchTool(),
        RegistryImageInfoTool(),
        # Rockcraft operations
        RockcraftInitTool(),
        RockcraftPackTool(),
        SkopeoRegistryPushTool(),
        # Environment
        ConciergePrepareTool(),
        ConciergeStatusTool(),
        # Git operations
        GitCloneTool(),
        GitInitTool(),
        GitStatusTool(),
        GitDiffTool(),
        GitLogTool(),
        GitAddTool(),
        GitCommitTool(),
        GitPushTool(),
        GitBranchTool(),
        GitCheckoutTool(),
        GitStashTool(),
        # GitHub operations
        GhRepoCreateTool(),
        GhRepoBootstrapTool(),
        GhPrCreateTool(),
        GhPrListTool(),
        GhPrViewTool(),
        GhIssueListTool(),
        PrReviewTool(),
        PrReviewReplyTool(),
        # Juju operations
        JujuStatusTool(),
        JujuDeployTool(),
        BundleDeployTool(),
        JujuRefreshTool(),
        JujuRelateTool(),
        JujuTrustTool(),
        JujuSSHTool(),
        JujuRunActionTool(),
        JujuAddModelTool(),
        JujuDestroyModelTool(),
        JujuOfferTool(),
        JujuConsumeTool(),
        JujuConfigTool(),
        JujuWaitTool(),
        CharmSyncTool(),
        JujuDispatchTool(),
        JujuListSecretsTool(),
        JujuShowSecretTool(),
        JujuReadRelationDataTool(),
        JujuGetAppConfigTool(),
        JujuListOffersTool(),
        JujuRemoveApplicationTool(),
        JujuShowUnitTool(),
        # Observability
        JujuDebugLogTool(),
        JujuStreamLogsTool(),
        TempoQueryTool(),
        LokiQueryTool(),
        GrafanaScreenshotTool(),
        TempoWaterfallTool(),
        # Inference snaps
        ListInferenceSnapsTool(),
        # Testing
        RunCharmTestsTool(),
        GenerateTestsTool(),
        HookBenchmarkTool(),
        FuzzTestTool(),
        TestReportTool(),
        ChaosTestTool(),
        ScalingTestTool(),
        UpgradeTestTool(),
        # Acceptance testing
        ActionExerciserTool(),
        RelationSmokeTool(),
        WorkloadEndpointTool(),
        ConfigVariationTool(),
        AcceptanceReportTool(),
        ConfigUnderLoadTool(),
        # Command runner
        RunCommandTool(),
        # Multi-charm workspace
        WorkspaceInfoTool(),
    ]

    # Tools with dependencies.
    if skills_index is not None:
        tools.append(LoadSkillTool(skills_index))
    if virtual_store is not None:
        tools.append(VirtualFileReadTool(virtual_store))
        tools.append(VirtualFileSearchTool(virtual_store))
    if provider is not None and state is not None and queue is not None:
        tools.append(PlanTasksTool(provider=provider, state=state, queue=queue))
        tools.append(ManageTasksTool(queue=queue))
    if memory_manager is not None:
        tools.extend(build_memory_tools(memory_manager))
    if mcp_registry is not None:
        for info in mcp_registry.aggregated_tools():
            tools.append(MCPTool(info, mcp_registry))

    return tools


if TYPE_CHECKING:
    from cantrip.agent.context import VirtualFileStore
    from cantrip.agent.memory import MemoryManager
    from cantrip.agent.skills import SkillsIndex
    from cantrip.mcp import MCPRegistry


__all__ = [
    "Tool",
    "ToolResult",
    "build_tools",
    "execute_tool",
    "tool_to_schema",
]
