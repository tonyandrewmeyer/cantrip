"""Agent tools."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from cantrip.agent.tools.acceptance import (
    AcceptanceReportTool,
    ActionExerciserTool,
    ConfigUnderLoadTool,
    ConfigVariationTool,
    RelationSmokeTool,
    WorkloadEndpointTool,
)
from cantrip.agent.tools.audit import CharmAuditTool
from cantrip.agent.tools.base import Tool, ToolResult, execute_tool, tool_to_schema
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
from cantrip.agent.tools.charmhub import (
    CharmhubInfoTool,
    CharmhubSearchTool,
)
from cantrip.agent.tools.charmlint_tool import CharmlintTool
from cantrip.agent.tools.environment import (
    ConciergePrepareTool,
    ConciergeStatusTool,
)
from cantrip.agent.tools.files import (
    EditFileTool,
    ListDirectoryTool,
    PathAwareTool,
    ReadFileTool,
    WriteFileTool,
)
from cantrip.agent.tools.fuzz import FuzzTestTool
from cantrip.agent.tools.git import (
    GitAddTool,
    GitCloneTool,
    GitCommitTool,
    GitDiffTool,
    GitInitTool,
    GitLogTool,
    GitPushTool,
    GitStatusTool,
)
from cantrip.agent.tools.github import (
    GhIssueListTool,
    GhPrCreateTool,
    GhRepoCreateTool,
)
from cantrip.agent.tools.glob import GlobTool
from cantrip.agent.tools.grep import GrepTool
from cantrip.agent.tools.inference import ListInferenceSnapsTool
from cantrip.agent.tools.juju import (
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
    JujuRunActionTool,
    JujuShowSecretTool,
    JujuSSHTool,
    JujuStatusTool,
    JujuWaitTool,
)
from cantrip.agent.tools.loadtest import GenerateLoadTestTool
from cantrip.agent.tools.multi_edit import MultiEditTool
from cantrip.agent.tools.observability import (
    JujuDebugLogTool,
    JujuStreamLogsTool,
    LokiQueryTool,
    TempoQueryTool,
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
from cantrip.agent.tools.registry import (
    RegistryImageInfoTool,
    RegistrySearchTool,
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


def build_tools(
    *,
    base_path: Path | None = None,
    skills_index: SkillsIndex | None = None,
    virtual_store: VirtualFileStore | None = None,
    provider: Any = None,
    state: Any = None,
    queue: Any = None,
) -> list[Tool]:
    """Build all agent tool instances.

    Centralises tool construction so callers do not need to import
    every tool class individually.  Parameters with dependencies
    (skills, virtual store, etc.) are passed in explicitly.
    """
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
        # GitHub operations
        GhRepoCreateTool(),
        GhPrCreateTool(),
        GhIssueListTool(),
        PrReviewTool(),
        PrReviewReplyTool(),
        # Juju operations
        JujuStatusTool(),
        JujuDeployTool(),
        JujuRefreshTool(),
        JujuRelateTool(),
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
        # Observability
        JujuDebugLogTool(),
        JujuStreamLogsTool(),
        TempoQueryTool(),
        LokiQueryTool(),
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

    return tools


if TYPE_CHECKING:
    from cantrip.agent.context import VirtualFileStore
    from cantrip.agent.skills import SkillsIndex


__all__ = [
    # Base
    "Tool",
    "ToolResult",
    "execute_tool",
    "tool_to_schema",
    # Audit
    "CharmAuditTool",
    "OperationalReadinessTool",
    # Benchmark and Fuzz
    "HookBenchmarkTool",
    "FuzzTestTool",
    # Files
    "PathAwareTool",
    "ReadFileTool",
    "WriteFileTool",
    "ListDirectoryTool",
    "EditFileTool",
    "GrepTool",
    "GlobTool",
    "MultiEditTool",
    # Charm
    "CharmcraftInitTool",
    "CharmcraftPackTool",
    "QuickPackTool",
    "CharmValidateTool",
    "CharmcraftFetchLibsTool",
    "AnalyseFrameworkTool",
    "GenerateTerraformTool",
    "ValidateTerraformTool",
    # Charmhub
    "CharmhubSearchTool",
    "CharmhubInfoTool",
    # Environment
    "ConciergePrepareTool",
    "ConciergeStatusTool",
    # Registry
    "RegistrySearchTool",
    "RegistryImageInfoTool",
    # Rockcraft
    "RockcraftInitTool",
    "RockcraftPackTool",
    "SkopeoRegistryPushTool",
    # Juju
    "JujuStatusTool",
    "JujuDeployTool",
    "JujuRefreshTool",
    "JujuRelateTool",
    "JujuSSHTool",
    "JujuRunActionTool",
    "JujuAddModelTool",
    "JujuDestroyModelTool",
    "JujuOfferTool",
    "JujuConfigTool",
    "JujuConsumeTool",
    "JujuWaitTool",
    "CharmSyncTool",
    "JujuDispatchTool",
    "JujuGetAppConfigTool",
    "JujuListOffersTool",
    "JujuListSecretsTool",
    "JujuReadRelationDataTool",
    "JujuShowSecretTool",
    # Git
    "GitCloneTool",
    "GitInitTool",
    "GitStatusTool",
    "GitDiffTool",
    "GitLogTool",
    "GitAddTool",
    "GitCommitTool",
    "GitPushTool",
    # GitHub
    "GhRepoCreateTool",
    "GhPrCreateTool",
    "GhIssueListTool",
    "PrReviewTool",
    "PrReviewReplyTool",
    # Observability
    "JujuDebugLogTool",
    "TempoQueryTool",
    "LokiQueryTool",
    # Testing
    "RunCharmTestsTool",
    "GenerateTestsTool",
    "HookBenchmarkTool",
    "FuzzTestTool",
    "TestReportTool",
    "ChaosTestTool",
    "ScalingTestTool",
    "UpgradeTestTool",
    # Acceptance testing
    "ActionExerciserTool",
    "RelationSmokeTool",
    "WorkloadEndpointTool",
    "ConfigVariationTool",
    "AcceptanceReportTool",
    "ConfigUnderLoadTool",
    # Planning
    "PlanTasksTool",
    # Task management
    "ManageTasksTool",
    # Skills
    "LoadSkillTool",
    # Virtual files
    "VirtualFileReadTool",
    "VirtualFileSearchTool",
    # Publishing
    "CharmcraftUploadTool",
    "CharmcraftReleaseTool",
    "GenerateReadmeTool",
    "GenerateIconTool",
    "GenerateDocsTool",
    "GenerateDiagramTool",
    "GenerateLoadTestTool",
    # Demo
    "ShowboatTool",
    "RodneyTool",
    # Web
    "WebFetchTool",
    "WebSearchTool",
    # Command runner
    "RunCommandTool",
    # Inference snaps
    "ListInferenceSnapsTool",
]
